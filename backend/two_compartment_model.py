import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score
from scipy.integrate import solve_ivp
from typing import Tuple
import matplotlib.pyplot as plt
from io import BytesIO
from typing import Tuple, List, Dict, Optional
from matplotlib.patches import Rectangle

# =============================================================================
# 1. Pre-fit QC & Preprocessing 
# =============================================================================

def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    - Ensure required columns exist and are numeric
    - Sort by time, drop duplicates
    - Warn on non-positive values
    """
    df = df.rename(columns={c: c.lower() for c in df.columns})

    if 'time' not in df or 'concentration' not in df:
        raise ValueError("Missing 'time' or 'concentration' column.")
    
    df['time'] = pd.to_numeric(df['time'], errors='coerce')
    df['concentration'] = pd.to_numeric(df['concentration'], errors='coerce')

    df = df.dropna(subset=['time','concentration'])

    if (df['time'] < 0).any():  print("Warning: negative time values found.")
    if (df['concentration'] <= 0).any():  print("Warning: non-positive concentration found.")

    return df.sort_values('time').drop_duplicates('time')

# =============================================================================
# 2. Model function: two-compartment
# =============================================================================
def model_two_comp(t: np.ndarray,
                   A: float, alpha: float,
                   B: float, beta: float) -> np.ndarray:
    """
    Solve C(t) = A*exp(-alpha*t) + B*exp(-beta*t)
    """
    return A * np.exp(-alpha * t) + B * np.exp(-beta * t)

# =============================================================================
# 3. Fit routine using SciPy curve_fit
# =============================================================================
def fit_two_compartment(
    t: np.ndarray,
    C: np.ndarray,
    dose: float,
    A0: float = None,
    alpha0: float = 1.0,
    B0: float = None,
    beta0: float = 0.1
) -> dict:
    """
    - Fit macro-constants A, alpha, B, beta by nonlinear least squares
    - Returns popt & pcov
    """
    # initialize A0,B0 so that A0 + B0 ≈ C[0]
    if A0 is None or B0 is None:
        C0 = C.max()
        A0 = 0.7 * C0
        B0 = 0.3 * C0

    def wrapper(t, A, alpha, B, beta):
        return model_two_comp(t, A, alpha, B, beta)

    try:
        popt, pcov = curve_fit(
            wrapper, 
            t, 
            C, 
            p0=[A0, alpha0, B0, beta0],
            bounds=(0, np.inf), # enforce non‐negative parameters
            maxfev=5000 # bump up max evaluations
        )
    except RuntimeError as e:
        # re‐raise with more context
        raise RuntimeError(
            f"Two‐compartment fit failed to converge after 5000 calls: {e}"
        )

    A_fit, alpha_fit, B_fit, beta_fit = popt
    se = np.sqrt(np.diag(pcov))  # [SE(A), SE(alpha), SE(B), SE(beta)]

    # 95% CIs
    z = 1.96
    A_ci     = (A_fit     - z*se[0], A_fit     + z*se[0])
    alpha_ci = (alpha_fit - z*se[1], alpha_fit + z*se[1])
    B_ci     = (B_fit     - z*se[2], B_fit     + z*se[2])
    beta_ci  = (beta_fit  - z*se[3], beta_fit  + z*se[3])

    return {
        'A': A_fit, 'A_se': se[0], 'A_ci': A_ci,
        'alpha': alpha_fit, 'alpha_se': se[1], 'alpha_ci': alpha_ci,
        'B': B_fit, 'B_se': se[2], 'B_ci': B_ci,
        'beta': beta_fit, 'beta_se': se[3], 'beta_ci': beta_ci,
        'pcov': pcov.tolist()
    }

# =============================================================================
# 4. Derived PK parameters for two‐compartment
# =============================================================================
def compute_pk_parameters_two(
    fit: dict,
    dose: float
) -> dict:
    """
    Compute:
      - C0 = A + B
      - half‐lives t1/2,α & t1/2,β
      - AUC = A/α + B/β
      - CL = dose/AUC
      - Vc = dose/(A+B)
      - MRT = (A/α**2 + B/β**2) / (A/α + B/β)
    """
    A     = fit['A']
    alpha = fit['alpha']
    B     = fit['B']
    beta  = fit['beta']

    C0      = A + B
    t_half_α = np.log(2) / alpha
    t_half_β = np.log(2) / beta
    AUC     = A/alpha + B/beta
    CL      = dose / AUC
    Vc      = dose / C0
    MRT     = (A/alpha**2 + B/beta**2) / (A/alpha + B/beta)

    return {
        'C0': C0,
        't_half_alpha': t_half_α,
        't_half_beta':  t_half_β,
        'AUC':   AUC,
        'CL':    CL,
        'Vc':    Vc,
        'MRT':   MRT
    }

# =============================================================================
# 5. Goodness‐of‐fit metrics
# =============================================================================
def compute_gof_two(
    t: np.ndarray,
    C: np.ndarray,
    fit: dict,
) -> dict:
    C_pred = model_two_comp(t,
                            fit['A'], fit['alpha'],
                            fit['B'], fit['beta'])
    r2    = r2_score(C, C_pred)
    resid = C - C_pred
    n = len(C); k = 4
    RSS = np.sum(resid**2)
    AIC = n * np.log(RSS/n) + 2*k
    return {
        'R2': r2,
        'resid_mean': np.mean(resid),
        'resid_std':  np.std(resid),
        'AIC': AIC
    }

# =============================================================================
# 6. Visualization: linear & semilog plots
# =============================================================================
def plot_fit_two(
    t: np.ndarray,
    C: np.ndarray,
    fit: dict,
    k10: float, k12: float, k21: float,
    V1: float, V2: float,
    dosing: Optional[List[Dict]] = None
) -> Tuple[BytesIO, BytesIO, BytesIO, BytesIO]:
    """
    Returns (buf_lin, buf_log) PNG buffers, each overlaid with:
      • total concentration  C_total(t) = A e^{-αt} + B e^{-βt}
      • central      C1(t)
      • peripheral   C2(t)
    """
    # unpack fit
    A, α, B, β = fit['A'], fit['alpha'], fit['B'], fit['beta']
    
    def odes(t, y):
        X1, X2 = y
        dX1 = - (k10 + k12)*X1 + k21*X2
        dX2 =   k12*X1 - k21*X2
        return [dX1, dX2]

    # initial amounts in compartments
    C0_total = A + B
    X1_0 = C0_total * V1
    X2_0 = 0.0
    sol = solve_ivp(odes, [t.min(), t.max()], [X1_0, X2_0],
                    t_eval=np.linspace(t.min(), t.max(), 200))
    t_sim = sol.t
    C1 = sol.y[0] / V1
    C2 = sol.y[1] / V2

    # compute total‐conc fit
    t_line = np.linspace(t.min(), t.max(), 200)
    C_tot  = model_two_comp(t_line, A, α, B, β)

    # 1) Linear total‐conc
    buf_lin = BytesIO()

    plt.figure()
    plt.scatter(t, C, label='Observed', alpha=0.6)
    t_line = np.linspace(t.min(), t.max(), 200)
    plt.plot(t_line, C_tot, 'r--', label='Total fit')
    plt.xlabel('Time')
    plt.ylabel('Concentration')
    plt.legend()
    plt.title('Two‐Compartment Fit (Linear)')
    plt.savefig(buf_lin, format='png')
    plt.close()
    buf_lin.seek(0)

    # 2) Semilog total‐conc
    buf_log = BytesIO()

    plt.figure()
    plt.scatter(t, C, label='Observed', alpha=0.6)
    plt.plot(t_line, C_tot, 'r--', label='Total fit')
    plt.yscale('log')
    plt.xlabel('Time')
    plt.ylabel('Concentration (log)')
    plt.legend()
    plt.title('Two‐Compartment Fit (Semilog)')
    plt.savefig(buf_log, format='png')
    plt.close()
    buf_log.seek(0)

    # 3) Mechanistic central vs. peripheral (linear)
    buf_mech = BytesIO()

    plt.figure()
    plt.plot(t_sim, C1, 'b-',  label='Central C1(t)')
    plt.plot(t_sim, C2, 'g--', label='Peripheral C2(t)')
    plt.xlabel('Time')
    plt.ylabel('Concentration')
    plt.title('Two-Compartment Mechanistic Compartments')
    plt.legend()
    plt.savefig(buf_mech, format='png')
    plt.close()
    buf_mech.seek(0)

    # 4) Dosing timeline
    buf_dose = BytesIO()
    plt.figure()
    ax = plt.gca()
    tmin, tmax = float(np.min(t)), float(np.max(t))
    ax.set_xlim(tmin, tmax)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xlabel('Time')
    ax.set_title('Dosing Timeline')

    events = dosing if dosing else [{"time": 0.0, "dose": (fit['A']+fit['B'])*V1}]
    has_bolus = False
    has_inf   = False

    for ev in events:
        ti = float(ev.get("time", 0.0))
        if "Tinf" in ev and ev["Tinf"] is not None and ev["Tinf"] > 0:
            width = float(ev["Tinf"])
            ax.add_patch(Rectangle((ti, 0.15), width, 0.7, alpha=0.3))
            has_inf = True
        else:
            ax.vlines(ti, 0.1, 0.9)
            has_bolus = True
            
    labels = []
    if has_bolus: labels.append("bolus")
    if has_inf:   labels.append("infusion")
    if labels:
        ax.text(0.99, 0.85, " + ".join(labels), transform=ax.transAxes,
                ha="right", va="center", fontsize=9)

    plt.tight_layout()
    plt.savefig(buf_dose, format='png')
    plt.close()
    buf_dose.seek(0)

    return buf_lin, buf_log, buf_mech, buf_dose