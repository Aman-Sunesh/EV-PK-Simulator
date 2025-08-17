import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score
import matplotlib.pyplot as plt
from io import BytesIO
from typing import List, Dict, Optional, Tuple
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
    # normalize column names
    df = df.rename(columns={c: c.lower() for c in df.columns})

    # required keys
    if 'time' not in df or 'concentration' not in df:
        raise ValueError("Missing 'time' or 'concentration' column.")

    # convert to numeric
    df['time'] = pd.to_numeric(df['time'], errors='coerce')
    df['concentration'] = pd.to_numeric(df['concentration'], errors='coerce')

    # drop rows with NaN
    df = df.dropna(subset=['time', 'concentration'])

    # warn on <=0
    if (df['time'] < 0).any():
        print("Warning: negative time values found.")

    if (df['concentration'] <= 0).any():
        print("Warning: non-positive concentration found.")

    # sort & dedupe
    df = df.sort_values('time').drop_duplicates('time')
    return df

# =============================================================================
# 2. Model function: one-compartment first-order elimination
# =============================================================================
def model_one_comp(t: np.ndarray, Vd: float, kel: float, dose: float) -> np.ndarray:
    """
    Solve C(t) = (dose / Vd) * exp(-kel * t)
    """
    C0 = dose / Vd
    return C0 * np.exp(-kel * t)

# =============================================================================
# 3. Fit routine using SciPy curve_fit
# =============================================================================
def fit_one_compartment(
    t: np.ndarray,
    C: np.ndarray,
    dose: float,
    Vd0: float = 1.0,
    kel0: float = 0.1
) -> dict:
    """
    - Fit Vd and kel by nonlinear least squares
    - Return fitted params and covariance
    """
    # wrapper for curve_fit
    def wrapper(t, Vd, kel):
        return model_one_comp(t, Vd, kel, dose)

    # perform fit 
    popt, pcov = curve_fit(wrapper, t, C, p0=[Vd0, kel0])

    # extract fitted parameters & SEs
    Vd_fit, kel_fit = popt
    se = np.sqrt(np.diag(pcov))    # [SE(Vd), SE(kel)]

    # 95% confidence interval multiplier (standard normal)
    z = 1.96
    Vd_ci = (Vd_fit - z * se[0], Vd_fit + z * se[0])
    kel_ci = (kel_fit - z * se[1], kel_fit + z * se[1])

    return {
        'Vd': Vd_fit,
        'Vd_se': se[0],
        'Vd_ci': Vd_ci,
        'kel': kel_fit,
        'kel_se': se[1],
        'kel_ci': kel_ci,
        'pcov': pcov.tolist()
    }

# =============================================================================
# 4. Derived PK parameters (with error propagation & 95% CIs)
# =============================================================================
def compute_pk_parameters(fit: dict, dose: float) -> dict:
    """
    Compute Cl, t_half, C0, AUC, MRT and their SEs & 95% CIs
    using delta-method error propagation from fit['pcov'].
    """

    Vd = fit['Vd']
    kel = fit['kel']
    pcov = np.asarray(fit['pcov'], dtype=float)  # shape (2,2): [[varVd, cov], [cov, varKel]]
    varVd, varKel = pcov[0, 0], pcov[1, 1]
    covVdKel      = pcov[0, 1]

    # point estimates
    Cl = kel * Vd
    t_half = np.log(2) / kel
    C0 = dose / Vd
    AUC = C0 / kel
    MRT = 1.0 / kel

    # partial derivatives
    dCl_dVd    = kel
    dCl_dkel   = Vd
    dt_half_dkel = -np.log(2) / (kel**2)
    dC0_dVd    = -dose / (Vd**2)
    dAUC_dVd   = -dose / (Vd**2 * kel)
    dAUC_dkel  = -dose / (Vd * kel**2)
    dMRT_dkel  = -1.0 / (kel**2)

    # variances via delta method
    varCl   = (dCl_dVd**2)*varVd + (dCl_dkel**2)*varKel + 2*dCl_dVd*dCl_dkel*covVdKel
    var_t_half = (dt_half_dkel**2) * varKel
    varC0   = (dC0_dVd**2) * varVd
    varAUC  = (dAUC_dVd**2)*varVd + (dAUC_dkel**2)*varKel + 2*dAUC_dVd*dAUC_dkel*covVdKel
    varMRT  = (dMRT_dkel**2) * varKel

    # standard errors
    seCl     = np.sqrt(varCl)
    se_t_half= np.sqrt(var_t_half)
    seC0     = np.sqrt(varC0)
    seAUC    = np.sqrt(varAUC)
    seMRT    = np.sqrt(varMRT)

    # 95% CI multiplier
    z = 1.96
    Cl_ci     = (Cl     - z*seCl,     Cl     + z*seCl)
    t_half_ci = (t_half - z*se_t_half, t_half + z*se_t_half)
    C0_ci     = (C0     - z*seC0,     C0     + z*seC0)
    AUC_ci    = (AUC    - z*seAUC,    AUC    + z*seAUC)
    MRT_ci    = (MRT    - z*seMRT,    MRT    + z*seMRT)

    return {
        'Cl': Cl,
        'Cl_se': seCl,
        'Cl_ci': Cl_ci,
        't_half': t_half,
        't_half_se': se_t_half,
        't_half_ci': t_half_ci,
        'C0': C0,
        'C0_se': seC0,
        'C0_ci': C0_ci,
        'AUC': AUC,
        'AUC_se': seAUC,
        'AUC_ci': AUC_ci,
        'MRT': MRT,
        'MRT_se': seMRT,
        'MRT_ci': MRT_ci
    }

# =============================================================================
# 5. Goodness-of-fit metrics
# =============================================================================
def compute_gof(t: np.ndarray, C: np.ndarray, fit: dict, dose: float) -> dict:
    """
    Compute R2, residual stats, and AIC for the one-compartment fit.
    """
    # predicted concentrations
    C_pred = model_one_comp(t, fit['Vd'], fit['kel'], dose)

    # R-squared
    r2 = r2_score(C, C_pred)

    # residuals
    resid = C - C_pred
    resid_mean = np.mean(resid)
    resid_std  = np.std(resid)

    # AIC calculation: AIC = n*ln(RSS/n) + 2*k
    n = len(C)
    k = 2  # number of estimated parameters: Vd and kel
    RSS = np.sum(resid**2)
    aic = n * np.log(RSS / n) + 2 * k

    return {
        'R2': r2,
        'resid_mean': resid_mean,
        'resid_std': resid_std,
        'AIC': aic
    }

# =============================================================================
# 6. Visualization: linear & semilog plots
# =============================================================================
def plot_fit(
    t: np.ndarray,
    C: np.ndarray,
    fit: dict,
    dose: float,
    dosing: Optional[List[Dict]] = None
) -> Tuple[BytesIO, BytesIO, BytesIO]:
    """
    Generate three PNG plots and return as binary buffers:
      • Linear concentration–time plot
      • Semilog (log-Y) concentration–time plot
      • Dosing timeline strip (bolus stems, infusion windows)

    Returns:
      (buf_lin: BytesIO, buf_log: BytesIO, buf_dose: BytesIO)
    """
    # linear plot
    buf_lin = BytesIO()

    plt.figure()
    plt.scatter(t, C, label='Observed')
    t_line = np.linspace(t.min(), t.max(), 100)
    plt.plot(t_line, model_one_comp(t_line, fit['Vd'], fit['kel'], dose), 'r--', label='Fit')
    plt.xlabel('Time')
    plt.ylabel('Concentration')
    plt.legend()
    plt.title('One-Compartment Fit')
    plt.savefig(buf_lin, format='png')
    plt.close()
    buf_lin.seek(0)

    # semilog plot
    buf_log = BytesIO()

    plt.figure()
    plt.scatter(t, C, label='Observed')
    plt.plot(t_line, model_one_comp(t_line, fit['Vd'], fit['kel'], dose), 'r--', label='Fit')
    plt.yscale('log')
    plt.xlabel('Time')
    plt.ylabel('Concentration (log)')
    plt.legend()
    plt.title('Semilog Plot')
    plt.savefig(buf_log, format='png')
    plt.close()
    buf_log.seek(0)
    
    # dosing timeline 
    buf_dose = BytesIO()
    plt.figure()
    ax = plt.gca()
    tmin, tmax = float(np.min(t)), float(np.max(t))
    ax.set_xlim(tmin, tmax)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xlabel('Time')
    ax.set_title('Dosing Timeline')

    # Default: single bolus at t=0 if nothing provided
    events = dosing if dosing else [{"time": 0.0, "dose": dose}]
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

    # simple legend
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

    return buf_lin, buf_log, buf_dose