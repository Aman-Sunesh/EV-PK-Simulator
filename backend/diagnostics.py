# diagnostics.py
#
# ──────────────────────────────────────────────────────────────────────────────
# Plotting utilities for PK model diagnostics.
#
# Provides:
#  • plot_residuals(...) → PNG buffer of residuals vs. time
#  • plot_vpc(...)       → PNG buffer of a Visual Predictive Check (5–95% band)
#
# Helpers:
#  • _params_from_fit(model, fit) → parameter vector in canonical order
#  • _pcov_from_fit(model, fit, params?) → positive-semidefinite covariance
#  • _nearest_psd(mat) → clips eigenvalues to ensure PSD
#  • _pred(model, t, p, dose) → model prediction wrapper (1c/2c/3c)
#
# Notes:
#  • Uses macro parameters for 2c/3c (A, α, B, β, [C, γ]); 1c uses (Vd, kel).
#  • Ensures covariance is PSD; falls back to a diagonal ridge if needed.
#  • Enforces parameter positivity on sampled draws to avoid invalid kinetics.
#  • Returns BytesIO buffers (PNG) suitable for embedding in PDF reports.
# ──────────────────────────────────────────────────────────────────────────────

import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from typing import Dict, Optional, List

from one_compartment_model import model_one_comp
from two_compartment_model import model_two_comp
from three_compartment_model import model_three_comp

def _params_from_fit(model: str, fit: Dict) -> np.ndarray:
    if model == "1c":  return np.array([fit["Vd"], fit["kel"]], dtype=float)
    if model == "2c":  return np.array([fit["A"], fit["alpha"], fit["B"], fit["beta"]], dtype=float)
    if model == "3c":  return np.array([fit["A"], fit["alpha"], fit["B"], fit["beta"], fit["C"], fit["gamma"]], dtype=float)
    raise ValueError("model must be '1c','2c','3c'")

def _nearest_psd(mat: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    # Symmetrize and clip eigenvalues to ensure PSD
    S = 0.5 * (mat + mat.T)
    w, V = np.linalg.eigh(S)
    w = np.clip(w, eps, None)
    return V @ np.diag(w) @ V.T


def _pcov_from_fit(model: str, fit: Dict, params: Optional[np.ndarray] = None) -> np.ndarray:
    pcov = None
    if "pcov" in fit:
        pcov = np.asarray(fit["pcov"], dtype=float)

    # Fallback if missing/invalid/NaN
    if pcov is None or pcov.ndim != 2 or pcov.shape[0] != pcov.shape[1] or not np.all(np.isfinite(pcov)):
        if params is None:
            params = _params_from_fit(model, fit)
        s = np.maximum(np.abs(params) * 0.1, 1e-6)
        pcov = np.diag(s**2)

    # Make PSD and add tiny ridge for stability
    try:
        pcov = _nearest_psd(pcov)
    except Exception:
        if params is None:
            params = _params_from_fit(model, fit)
        s = np.maximum(np.abs(params) * 0.1, 1e-6)
        pcov = np.diag(s**2)
    pcov = pcov + 1e-12 * np.eye(pcov.shape[0])

    return pcov

def _pred(model: str, t: np.ndarray, p: np.ndarray, dose: Optional[float]) -> np.ndarray:
    if model == "1c":
        return model_one_comp(t, Vd=p[0], kel=p[1], dose=float(dose or 1.0))
    if model == "2c":
        return model_two_comp(t, A=p[0], alpha=p[1], B=p[2], beta=p[3])
    if model == "3c":
        return model_three_comp(t, A=p[0], alpha=p[1], B=p[2], beta=p[3], C=p[4], gamma=p[5])

    raise ValueError("bad model")

def plot_residuals(t: np.ndarray, C: np.ndarray, fit: Dict, model: str, dose: Optional[float]) -> BytesIO:
    p = _params_from_fit(model, fit)
    pred = _pred(model, t, p, dose)
    resid = C - pred
    buf = BytesIO()
    plt.figure()
    plt.axhline(0.0, lw=1, alpha=0.6)
    plt.scatter(t, resid, alpha=0.7)
    plt.xlabel("Time"); plt.ylabel("Residual")
    plt.title("Residuals vs Time")
    plt.tight_layout(); plt.savefig(buf, format="png"); plt.close(); buf.seek(0)

    return buf

def plot_vpc(t: np.ndarray, fit: Dict, model: str, dose: Optional[float],
             n_draws: int = 200, seed: Optional[int] = None) -> BytesIO:
    
    rng = np.random.default_rng(seed)
    p = _params_from_fit(model, fit)
    pcov = _pcov_from_fit(model, fit, p)

    # Robust sampling: try MVN; if it fails, fall back to independent normals
    try:
        draws = rng.multivariate_normal(p, pcov, size=n_draws, check_valid="ignore")
    except Exception:
        std = np.sqrt(np.clip(np.diag(pcov), 1e-12, None))
        draws = p + rng.normal(0.0, std, size=(n_draws, p.size))

    # enforce positivity
    draws = np.clip(draws, 1e-12, np.inf)
    grid = np.linspace(float(np.min(t)), float(np.max(t)), 200)
    M = np.empty((n_draws, grid.size), dtype=float)

    for i in range(n_draws):
        M[i] = _pred(model, grid, draws[i], dose)

    q5  = np.percentile(M, 5, axis=0)
    q50 = np.percentile(M, 50, axis=0)
    q95 = np.percentile(M, 95, axis=0)

    buf = BytesIO()
    plt.figure()
    plt.fill_between(grid, q5, q95, alpha=0.2, label="90% VPC band")
    plt.plot(grid, q50, linestyle="--", label="Median pred")
    plt.xlabel("Time"); plt.ylabel("Concentration")
    plt.title("Visual Predictive Check")
    plt.legend()
    plt.tight_layout(); plt.savefig(buf, format="png"); plt.close(); buf.seek(0)
    
    return buf
