import numpy as np
import pandas as pd
from scipy.optimize import curve_fit, least_squares
from sklearn.metrics import r2_score
from scipy.integrate import solve_ivp
import matplotlib.pyplot as plt
from io import BytesIO
from typing import Tuple, List, Dict, Optional
from matplotlib.patches import Rectangle

def _softplus(x):
    # strictly positive; numerically stable
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0.0)

def _softplus_inv(y):
    return np.log(np.expm1(np.maximum(y, 1e-12)))

def _softmax3(z):
    z = np.asarray(z, float)
    z = z - np.max(z)
    e = np.exp(z)
    return e / np.sum(e)

def _unpack_params(p):
    # p = [logC0, a1, a2, a3, z1, z2, z3]
    logC0, a1, a2, a3, z1, z2, z3 = p
    alpha = _softplus(a1) + 1e-4
    beta  = alpha + _softplus(a2)
    gamma = beta  + _softplus(a3)
    s1, s2, s3 = _softmax3([z1, z2, z3])
    C0 = np.exp(logC0)
    A = C0 * s1; B = C0 * s2; Cc = C0 * s3
    return C0, A, alpha, B, beta, Cc, gamma


# =============================================================================
# 1. Pre-fit QC & Preprocessing
# =============================================================================
def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if 'time' not in df or 'concentration' not in df:
        raise ValueError("Missing 'time' or 'concentration' column.")
    df['time'] = pd.to_numeric(df['time'], errors='coerce')
    df['concentration'] = pd.to_numeric(df['concentration'], errors='coerce')
    df = df.dropna(subset=['time','concentration'])
    if (df['time'] < 0).any():
        print("Warning: negative time values found.")
    if (df['concentration'] <= 0).any():
        print("Warning: non-positive concentration found.")
        # Drop non-positive rows to improve stability of tri-exponential fit
        df = df[df['concentration'] > 0].copy()
        
    return df.sort_values('time').drop_duplicates('time')


# =============================================================================
# 2. Model function: three-compartment (macro tri-exponential)
# =============================================================================
def model_three_comp(t: np.ndarray, A: float, alpha: float, B: float, beta: float, C: float, gamma: float) -> np.ndarray:
    return A*np.exp(-alpha*t) + B*np.exp(-beta*t) + C*np.exp(-gamma*t)


# =============================================================================
# 3. Fit routine (nonlinear least squares, nonnegative parameters)
# =============================================================================
def fit_three_compartment(
    t: np.ndarray,
    C: np.ndarray,
    dose: float,
    A0: float = None, alpha0: float = 3.0,
    B0: float = None, beta0: float  = 0.5,
    C0_: float = None, gamma0: float = 0.05
) -> dict:
    t = np.asarray(t, float); C = np.asarray(C, float)

    # keep strictly positive for log-scale fit
    m = C > 0
    t = t[m]; C = C[m]

    if t.size < 6:
        raise RuntimeError("Too few positive points for a stable three-compartment fit.")

    # C0 guess
    C0_guess = float(np.mean(C[t == 0])) if np.any(t == 0) else float(np.max(C))
    C0_guess = max(C0_guess, 1e-6)

    if A0 is None or B0 is None or C0_ is None:
        A0, B0, C0_ = 0.5*C0_guess, 0.35*C0_guess, 0.15*C0_guess

    def _seed(a_s, b_s, g_s, w=(0.6,0.3,0.1)):
        z = np.log(np.array(w, float))
        a1 = _softplus_inv(max(a_s - 1e-4, 1e-6))
        a2 = _softplus_inv(max(b_s - max(a_s,1e-4), 1e-6))
        a3 = _softplus_inv(max(g_s - max(b_s,1e-4), 1e-6))
        return np.array([np.log(C0_guess), a1, a2, a3, z[0], z[1], z[2]], float)

    starts = [
        _seed(alpha0,        beta0,        gamma0,        (0.60,0.30,0.10)),
        _seed(alpha0*1.5,    beta0*0.8,    gamma0*0.8,    (0.50,0.35,0.15)),
        _seed(alpha0*0.8,    beta0*1.2,    gamma0*1.2,    (0.40,0.40,0.20)),
        _seed(alpha0*2.0,    beta0,        gamma0*0.5,    (0.70,0.20,0.10)),
    ]

    eps = 1e-9
    y = np.log(C + eps)

    def _model(tarr, A, a, B, b, Cc, g):
        return A*np.exp(-a*tarr) + B*np.exp(-b*tarr) + Cc*np.exp(-g*tarr)

    def residuals(p):
        _, A, a, B, b, Cc, g = _unpack_params(p)
        Cp = _model(t, A, a, B, b, Cc, g)
        return np.log(Cp + eps) - y  # multiplicative errors

    best = None

    for p0 in starts:
        res = least_squares(
            residuals, p0, method="trf",
            loss="soft_l1", f_scale=0.1,
            max_nfev=20000, xtol=1e-10, ftol=1e-10, gtol=1e-10
        )
        if best is None or res.cost < best.cost:
            best = res

    # unpack solution
    C0_hat, A_hat, alpha_hat, B_hat, beta_hat, C_hat, gamma_hat = _unpack_params(best.x)

    # covariance (Gauss-Newton)
    n, k = y.size, best.x.size
    RSS = 2.0*best.cost
    s2 = RSS / max(n - k, 1)
    JTJ = best.jac.T @ best.jac

    try:
        Hinv = np.linalg.inv(JTJ + 1e-12*np.eye(k))
    except np.linalg.LinAlgError:
        Hinv = np.diag(np.full(k, (0.2)**2))

    cov_p = s2 * Hinv

    # delta-method draws → CIs on macros
    rng = np.random.default_rng(1234)

    try:
        draws = rng.multivariate_normal(best.x, cov_p, size=400, check_valid="ignore")
    except Exception:
        std = np.sqrt(np.clip(np.diag(cov_p), 1e-12, None))
        draws = best.x + rng.normal(0.0, std, size=(400, k))

    M = []

    for d in draws:
        try:
            _, A_d, a_d, B_d, b_d, C_d, g_d = _unpack_params(d)
            M.append([A_d, a_d, B_d, b_d, C_d, g_d])
        except Exception:
            pass

    M = np.asarray(M, float) if len(M) else np.empty((0,6))

    def _ci(i, est):
        if M.shape[0] < 20:
            d = 0.2*max(abs(est), 1e-6)
            return (est - 1.96*d, est + 1.96*d)
        lo, hi = np.percentile(M[:, i], [2.5, 97.5])
        return (float(lo), float(hi))

    return {
        'A': A_hat, 'A_se': None, 'A_ci': _ci(0, A_hat),
        'alpha': alpha_hat, 'alpha_se': None, 'alpha_ci': _ci(1, alpha_hat),
        'B': B_hat, 'B_se': None, 'B_ci': _ci(2, B_hat),
        'beta': beta_hat, 'beta_se': None, 'beta_ci': _ci(3, beta_hat),
        'C': C_hat, 'C_se': None, 'C_ci': _ci(4, C_hat),
        'gamma': gamma_hat, 'gamma_se': None, 'gamma_ci': _ci(5, gamma_hat),
        'pcov': cov_p.tolist()
    }


# =============================================================================
# 4. Derived PK parameters for three-compartment
# =============================================================================
def compute_pk_parameters_three(fit: dict, dose: float) -> dict:
    A = fit['A']; alpha = fit['alpha']
    B = fit['B']; beta  = fit['beta']
    C = fit['C']; gamma = fit['gamma']

    C0 = A + B + C
    t_half_alpha = np.log(2) / alpha if alpha > 0 else np.inf
    t_half_beta  = np.log(2) / beta  if beta  > 0 else np.inf
    t_half_gamma = np.log(2) / gamma if gamma > 0 else np.inf
    AUC = (A/alpha) + (B/beta) + (C/gamma)
    CL  = dose / AUC if AUC > 0 else np.nan
    Vc  = dose / C0 if C0 > 0 else np.nan
    MRT = (A/alpha**2 + B/beta**2 + C/gamma**2) / AUC if AUC > 0 else np.nan

    return {
        'C0': C0,
        't_half_alpha': t_half_alpha,
        't_half_beta':  t_half_beta,
        't_half_gamma': t_half_gamma,
        'AUC': AUC,
        'CL': CL,
        'Vc': Vc,
        'MRT': MRT
    }


# =============================================================================
# 5. Goodness-of-fit metrics
# =============================================================================
def compute_gof_three(t: np.ndarray, C: np.ndarray, fit: dict) -> dict:
    eps = 1e-9
    C_pred = model_three_comp(
        np.asarray(t, float),
        fit['A'], fit['alpha'], fit['B'], fit['beta'], fit['C'], fit['gamma']
    )
    y = np.log(np.clip(C, eps, None))
    yhat = np.log(np.clip(C_pred, eps, None))
    ss_res = np.sum((y - yhat)**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2_log = 1.0 - ss_res/ss_tot if ss_tot > 0 else np.nan
    n = y.size; k = 6
    sigma2 = ss_res / max(n,1)
    AIC = n*np.log(max(sigma2, 1e-300)) + 2*k
    return {'R2': float(r2_log), 'resid_mean': float(np.mean(y-yhat)), 'resid_std': float(np.std(y-yhat)), 'AIC': float(AIC)}

# =============================================================================
# 6. Visualization (total fit; mechanistic with micro constants if provided)
# =============================================================================
def plot_fit_three(
    t: np.ndarray, C: np.ndarray, fit: dict,
    k10: float, k12: float, k21: float, k13: float, k31: float,
    V1: float, V2: float, V3: float,
    dosing: Optional[List[Dict]] = None
) -> Tuple[BytesIO, BytesIO, BytesIO, BytesIO]:

    A, α, B, β, Cc, γ = fit['A'], fit['alpha'], fit['B'], fit['beta'], fit['C'], fit['gamma']
    t_line = np.linspace(t.min(), t.max(), 200)
    C_tot  = model_three_comp(t_line, A, α, B, β, Cc, γ)

    # 1) Linear plot
    buf_lin = BytesIO()
    plt.figure()
    plt.scatter(t, C, label='Observed', alpha=0.6)
    plt.plot(t_line, C_tot, 'r--', label='Total fit')
    plt.xlabel('Time'); plt.ylabel('Concentration')
    plt.legend(); plt.title('Three-Compartment Fit (Linear)')
    plt.savefig(buf_lin, format='png'); plt.close(); buf_lin.seek(0)

    # 2) Semilog plot
    buf_log = BytesIO()
    plt.figure()
    plt.scatter(t, C, label='Observed', alpha=0.6)
    plt.plot(t_line, C_tot, 'r--', label='Total fit')
    plt.yscale('log')
    plt.xlabel('Time'); plt.ylabel('Concentration (log)')
    plt.legend(); plt.title('Three-Compartment Fit (Semilog)')
    plt.savefig(buf_log, format='png'); plt.close(); buf_log.seek(0)

    # 3) Mechanistic central + two peripherals
    buf_mech = BytesIO()
    def odes(_t, y):
        X1, X2, X3 = y
        dX1 = - (k10 + k12 + k13)*X1 + k21*X2 + k31*X3
        dX2 = k12*X1 - k21*X2
        dX3 = k13*X1 - k31*X3
        return [dX1, dX2, dX3]

    C0_total = A + B + Cc
    X1_0 = C0_total * V1
    X2_0 = 0.0
    X3_0 = 0.0

    sol = solve_ivp(odes, [t.min(), t.max()], [X1_0, X2_0, X3_0],
                    t_eval=np.linspace(t.min(), t.max(), 200))
    t_sim = sol.t
    C1 = sol.y[0] / V1
    C2 = sol.y[1] / V2
    C3 = sol.y[2] / V3

    plt.figure()
    plt.plot(t_sim, C1, 'b-',  label='Central C1(t)')
    plt.plot(t_sim, C2, 'g--', label='Periph-2 C2(t)')
    plt.plot(t_sim, C3, 'm-.', label='Periph-3 C3(t)')
    plt.xlabel('Time'); plt.ylabel('Concentration')
    plt.title('Three-Compartment Mechanistic Compartments')
    plt.legend()
    plt.savefig(buf_mech, format='png'); plt.close(); buf_mech.seek(0)

    # 4) Dosing timeline
    buf_dose = BytesIO()
    plt.figure()
    ax = plt.gca()
    tmin, tmax = float(np.min(t)), float(np.max(t))
    ax.set_xlim(tmin, tmax); ax.set_ylim(0, 1)
    ax.set_yticks([]); ax.set_xlabel('Time'); ax.set_title('Dosing Timeline')
    events = dosing if dosing else [{"time": 0.0, "dose": C0_total*V1}]
    has_bolus = False; has_inf = False
    for ev in events:
        ti = float(ev.get("time", 0.0))
        if "Tinf" in ev and ev["Tinf"] is not None and ev["Tinf"] > 0:
            width = float(ev["Tinf"])
            ax.add_patch(Rectangle((ti, 0.15), width, 0.7, alpha=0.3))
            has_inf = True
        else:
            ax.vlines(ti, 0.1, 0.9); has_bolus = True
    labels = []
    if has_bolus: labels.append("bolus")
    if has_inf:   labels.append("infusion")
    if labels:
        ax.text(0.99, 0.85, " + ".join(labels), transform=ax.transAxes,
                ha="right", va="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(buf_dose, format='png'); plt.close(); buf_dose.seek(0)

    return buf_lin, buf_log, buf_mech, buf_dose
