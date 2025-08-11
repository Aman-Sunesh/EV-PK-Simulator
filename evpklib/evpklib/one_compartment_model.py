import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score
import matplotlib.pyplot as plt
from io import BytesIO

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
    df = df.rename(columns={c.lower(): c for c in df.columns})

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
        'pcov': pcov
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
    pcov = fit['pcov']   # 2×2 covariance: [[varVd, covVdKel], [covVdKel, varKel]]
    varVd, varKel = pcov[0,0], pcov[1,1]
    covVdKel  = pcov[0,1]

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
def plot_fit(t: np.ndarray, C: np.ndarray, fit: dict, dose: float) -> BytesIO:
    """
    Generate two PNG plots and return as binary buffer
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
    
    return buf_lin, buf_log