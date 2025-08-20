# uq.py
#
# ─────────────────────────────────────────────────────────────────────────────────────
# EV–PK Simulator — Parameter Uncertainty Quantification
#
# What this module provides
#  • bootstrap_uq(...): residual bootstrap → refit → parameter samples & CIs
#  • mcmc_uq(...): simple Metropolis–Hastings on (log-parameters)
#
# Helpers (internal)
#  • _pack(model, fit)  → (param_vector, pcov, names)
#  • _pred(model, t, p, dose) → model prediction at times t
#  • _refit(model, t, C, dose) → re-fit model to (t, C)
#
# Notes
#  • Supported models: "1c", "2c", "3c"
#  • For 2c/3c macro models, `dose` is unused by the predictor, but preserved
#    in the API and forwarded to the fitters for signature symmetry.
#  • Returned structures are JSON-serializable (lists, not ndarrays).
# ─────────────────────────────────────────────────────────────────────────────────────

import numpy as np
from typing import Dict, List, Tuple, Optional
from io import BytesIO

from one_compartment_model import model_one_comp, fit_one_compartment
from two_compartment_model import model_two_comp, fit_two_compartment
from three_compartment_model import model_three_comp, fit_three_compartment


def _pack(model: str, fit: Dict) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    if model == "1c":
        params = np.array([fit["Vd"], fit["kel"]], dtype=float)
        names  = ["Vd", "kel"]
        pcov   = np.asarray(fit["pcov"], dtype=float)
    elif model == "2c":
        params = np.array([fit["A"], fit["alpha"], fit["B"], fit["beta"]], dtype=float)
        names  = ["A", "alpha", "B", "beta"]
        pcov   = np.asarray(fit["pcov"], dtype=float)
    elif model == "3c":
        params = np.array([fit["A"], fit["alpha"], fit["B"], fit["beta"], fit["C"], fit["gamma"]], dtype=float)
        names  = ["A", "alpha", "B", "beta", "C", "gamma"]
        pcov   = np.asarray(fit["pcov"], dtype=float)
    else:
        raise ValueError("model must be '1c','2c','3c'")
    return params, pcov, names


def _pred(model: str, t: np.ndarray, p: np.ndarray, dose: Optional[float]) -> np.ndarray:
    if model == "1c":
        return model_one_comp(t, Vd=p[0], kel=p[1], dose=float(dose or 1.0))
    if model == "2c":
        return model_two_comp(t, A=p[0], alpha=p[1], B=p[2], beta=p[3])
    if model == "3c":
        return model_three_comp(t, A=p[0], alpha=p[1], B=p[2], beta=p[3], C=p[4], gamma=p[5])
    raise ValueError("bad model")


def _refit(model: str, t: np.ndarray, C: np.ndarray, dose: Optional[float]) -> Dict:
    if model == "1c":
        return fit_one_compartment(t, C, float(dose or 1.0))
    if model == "2c":
        return fit_two_compartment(t, C, float(dose or 1.0))
    if model == "3c":
        return fit_three_compartment(t, C, float(dose or 1.0))
    raise ValueError("bad model")


def bootstrap_uq(model: str, t: np.ndarray, C: np.ndarray, fit: Dict, dose: Optional[float],
                 n_boot: int = 200, rng: Optional[np.random.Generator] = None) -> Dict:
    """Residual bootstrap: C*_b = C_hat + resampled(residuals) → refit → param samples."""
    rng = rng or np.random.default_rng()
    p0, _, names = _pack(model, fit)
    C_hat = _pred(model, t, p0, dose)
    resid = C - C_hat
    P = np.zeros((n_boot, len(p0)), dtype=float)

    for b in range(n_boot):
        r = rng.choice(resid, size=resid.size, replace=True)
        Cb = C_hat + r
        fb = _refit(model, t, Cb, dose)
        P[b] = _pack(model, fb)[0]

    qs = np.quantile(P, [0.025, 0.5, 0.975], axis=0)

    return {
        "method": "bootstrap",
        "param_names": names,
        "samples": P.tolist(),
        "quantiles": {"2.5%": qs[0].tolist(), "50%": qs[1].tolist(), "97.5%": qs[2].tolist()}
    }


def mcmc_uq(model: str, t: np.ndarray, C: np.ndarray, fit: Dict, dose: Optional[float],
            n_samples: int = 2000, burn: int = 500, step_scale: float = 0.2,
            rng: Optional[np.random.Generator] = None) -> Dict:
    """
    Simple MH on log-parameters with Gaussian errors (sigma from residual SD).
    Positive params are enforced by sampling in log-space.
    """
    rng = rng or np.random.default_rng()
    p_map, pcov, names = _pack(model, fit)

    # sigma from residuals
    C_hat = _pred(model, t, p_map, dose)
    sigma = float(np.std(C - C_hat, ddof=min(len(p_map), max(1, len(t)-len(p_map)))))

    # proposal std from diagonal or 10% relative fallback
    diag = np.sqrt(np.abs(np.diag(pcov))) if pcov.shape[0] == len(p_map) else np.maximum(1e-8, 0.1*np.abs(p_map))
    prop_sd = step_scale * np.where(diag > 0, diag, np.maximum(1e-8, 0.1*np.abs(p_map)))

    def loglike(p_lin: np.ndarray) -> float:
        pred = _pred(model, t, p_lin, dose)
        res  = C - pred
        return -0.5*np.sum((res/sigma)**2) - len(t)*np.log(max(1e-12, sigma))

    def logprior(p_lin: np.ndarray) -> float:
        # vague improper prior on log-params → flat prior on log-scale
        return 0.0

    p = np.maximum(1e-12, p_map.copy())
    logp = loglike(p) + logprior(p)
    chain = np.zeros((n_samples, len(p)), dtype=float)
    acc = 0

    for i in range(n_samples):
        # propose in log-space
        z = np.log(p)
        z_prop = z + rng.normal(scale=prop_sd/np.maximum(1e-12, p))  # approx relative step
        p_prop = np.exp(z_prop)
        ll_prop = loglike(p_prop) + logprior(p_prop)

        if np.log(rng.random()) < (ll_prop - logp):
            p, logp = p_prop, ll_prop
            acc += 1

        chain[i] = p

    draws = chain[burn:]
    qs = np.quantile(draws, [0.025, 0.5, 0.975], axis=0)
    
    return {
        "method": "mcmc",
        "accept_rate": acc / max(1, n_samples),
        "param_names": names,
        "samples": draws.tolist(),
        "quantiles": {"2.5%": qs[0].tolist(), "50%": qs[1].tolist(), "97.5%": qs[2].tolist()}
    }
