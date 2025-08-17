import numpy as np
from typing import Dict, List, Tuple, Optional
from scipy.stats.qmc import Sobol

from pk_routes_one_comp import simulate_one_comp_route
from pk_routes_two_comp import simulate_two_comp_route
from pk_routes_three_comp import simulate_three_comp_route
from dosing_program import expand_program

Metric = str  # "Cmax" | "AUC" | "Tmax"

def _sim(model: str, route: str, params: Dict, dosing, repeat, program, t_end: float, dt: float) -> Dict:
    if model == "1c":
        return simulate_one_comp_route(route, params, dosing, repeat, t_end, dt)
    if model == "2c":
        return simulate_two_comp_route(route, params, dosing, repeat, t_end, dt)
    if model == "3c":
        return simulate_three_comp_route(route, params, dosing, repeat, t_end, dt)
    raise ValueError("model must be '1c','2c','3c'")

def _metric(sim_out: Dict, name: Metric) -> float:
    s = sim_out["summary"]

    if name not in s:
        raise ValueError(f"metric {name} not in simulation summary")
    return float(s[name])

def local_sensitivity(model: str, route: str, params: Dict, vary: Dict[str, float],
                      dosing=None, repeat=None, program=None, t_end: float=24.0, dt: float=0.1,
                      metric: Metric="Cmax", eps_rel: float=1e-3) -> Dict:

    base = _sim(model, route, params, dosing, repeat, program, t_end, dt)
    y0 = _metric(base, metric)
    out = {}

    for pname, rel in vary.items():
        if pname not in params:
            continue

        p0 = float(params[pname])
        h = max(eps_rel*abs(p0), 1e-8)
        p_plus  = dict(params); p_plus[pname]  = p0 + h
        p_minus = dict(params); p_minus[pname] = max(1e-12, p0 - h)
        y_plus  = _metric(_sim(model, route, p_plus, dosing, repeat, program, t_end, dt),  metric)
        y_minus = _metric(_sim(model, route, p_minus, dosing, repeat, program, t_end, dt), metric)
        dy_dp = (y_plus - y_minus) / (2*h)

        # normalized sensitivity: (p/y) * dy/dp
        out[pname] = float((p0 / max(1e-12, y0)) * dy_dp)

    return {"method": "local", "metric": metric, "sensitivities": out, "baseline": y0}

def _rank(a: np.ndarray) -> np.ndarray:
    return np.argsort(np.argsort(a)) / max(1, len(a)-1)

def _prcc(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Partial rank correlation coefficients using linear regression on ranks."""
    # rank-transform
    R = np.apply_along_axis(_rank, 0, X)
    rY = _rank(y)

    # regress each param on the others → residuals; same for y
    from numpy.linalg import lstsq

    n, k = R.shape
    S = np.zeros(k)

    for j in range(k):
        idx = [i for i in range(k) if i != j]
        Xj = np.c_[np.ones(n), R[:, idx]]
        beta, *_ = lstsq(Xj, R[:, j], rcond=None)
        res_p = R[:, j] - Xj @ beta
        Xy = np.c_[np.ones(n), R]
        betay, *_ = lstsq(Xy, rY, rcond=None)
        res_y = rY - Xy @ betay
        S[j] = np.corrcoef(res_p, res_y)[0, 1]

    return S

def global_prcc_sensitivity(model: str, route: str, params: Dict, ranges: Dict[str, Tuple[float, float]],
                            N: int=512, dosing=None, repeat=None, program=None,
                            t_end: float=24.0, dt: float=0.1, metric: Metric="Cmax") -> Dict:
    
    names = list(ranges.keys())
    k = len(names)

    # Sobol quasi-random sampling in [0,1]^k then map to ranges
    sampler = Sobol(d=k, scramble=True)

    U = sampler.random_base2(int(np.ceil(np.log2(max(2, N)))))  # nearest power of 2
    X = np.empty_like(U)

    for j, name in enumerate(names):
        lo, hi = map(float, ranges[name])
        X[:, j] = lo + (hi - lo) * U[:, j]

    # evaluate
    y = np.zeros(X.shape[0], dtype=float)

    for i in range(X.shape[0]):
        p = dict(params)
        for j, name in enumerate(names):
            p[name] = float(X[i, j])
        y[i] = _metric(_sim(model, route, p, dosing, repeat, program, t_end, dt), metric)

    S = _prcc(X, y)

    return {"method": "global_prcc", "metric": metric, "names": names, "PRCC": S.tolist()}


def _dispatch_sim(model: str, route: str, params: Dict,
                  dosing, repeat, program, t_end: float, dt: float) -> Dict:
    """Internal: mirror main._sim without importing main.py"""
    if program:
        program_dosing = expand_program(program, route, params.get("Tinf"))
        
        if isinstance(program_dosing, tuple) and len(program_dosing) == 1 and isinstance(program_dosing[0], list):
            dosing = program_dosing[0]
        else:
            dosing = program_dosing
        repeat = None

    if model == "1c":
        return simulate_one_comp_route(route, params, dosing, repeat, t_end, dt)
    elif model == "2c":
        return simulate_two_comp_route(route, params, dosing, repeat, t_end, dt)
    elif model == "3c":
        return simulate_three_comp_route(route, params, dosing, repeat, t_end, dt)

    raise ValueError("model must be '1c','2c','3c'")

def _eval_metric(result: Dict, metric: str) -> float:
    s = result.get("summary", {})

    if metric in s:
        return float(s[metric])

    # convenient fallbacks
    if metric.lower() == "cmax": return float(s.get("Cmax", np.nan))
    if metric.lower() == "auc":  return float(s.get("AUC",  np.nan))
    raise ValueError(f"Unknown/unsupported metric '{metric}'")

def global_sobol_sensitivity(
    model: str, route: str, params: Dict, ranges: Dict[str, Dict],
    N: int, dosing, repeat, program, t_end: float, dt: float, metric: str = "Cmax",
    seed: Optional[int] = None
) -> Dict:
    """
    Variance-based Sobol indices (first-order Si and total-order STi) via
    Saltelli/Jansen estimators. No external deps.

      • Build two sample matrices A, B ~ U([lo,hi]) for d parameters.
      • For each i, form A_Bi (A with col i from B).
      • Si  = mean( f(B)*(f(A_Bi) - f(A)) ) / Var(f(A))
      • STi = mean( (f(A) - f(A_Bi))^2 ) / (2*Var(f(A)))
    """
    rng = np.random.default_rng(seed)

    # choose parameters & bounds
    keys = list(ranges.keys()) if ranges else list(params.keys())

    d = len(keys)
    if d == 0:
        raise ValueError("No parameters to vary for Sobol analysis")

    lo = np.zeros(d); hi = np.zeros(d)

    for j, k in enumerate(keys):
        base = float(params.get(k, 1.0))
        r = ranges.get(k, {}) if ranges else {}
        lo[j] = float(r.get("lo", 0.5*base if base > 0 else 0.1))
        hi[j] = float(r.get("hi", 1.5*base if base > 0 else 2.0))

        if not np.isfinite(lo[j]) or not np.isfinite(hi[j]) or hi[j] <= lo[j]:
            raise ValueError(f"Bad bounds for '{k}'")

    # sample A, B
    A = lo + (hi - lo) * rng.random((N, d))
    B = lo + (hi - lo) * rng.random((N, d))

    # evaluate f(A), f(B)
    fA = np.empty(N); fB = np.empty(N)

    for n in range(N):
        pA = dict(params); pB = dict(params)

        for j, k in enumerate(keys):
            pA[k] = float(A[n, j]); pB[k] = float(B[n, j])
        fA[n] = _eval_metric(_dispatch_sim(model, route, pA, dosing, repeat, program, t_end, dt), metric)
        fB[n] = _eval_metric(_dispatch_sim(model, route, pB, dosing, repeat, program, t_end, dt), metric)

    varY = float(np.var(fA, ddof=1))
    if varY <= 0 or not np.isfinite(varY):
        raise ValueError("Variance is zero or invalid; widen parameter ranges.")

    # per-parameter indices
    Si  = np.empty(d); STi = np.empty(d)
    for j in range(d):
        fAB = np.empty(N)
        for n in range(N):
            p = dict(params)
            # columns from A except j-th from B
            for m, k in enumerate(keys):
                p[k] = float(B[n, m] if m == j else A[n, m])
            fAB[n] = _eval_metric(_dispatch_sim(model, route, p, dosing, repeat, program, t_end, dt), metric)

        # Saltelli 2002 first-order
        Si[j]  = float(np.mean(fB * (fAB - fA)) / varY)

        # Jansen 1999 total-order
        STi[j] = float(np.mean((fA - fAB)**2) / (2.0 * varY))

    return {
        "method": "sobol",
        "N": int(N),
        "metric": metric,
        "parameters": keys,
        "first_order": {k: float(Si[i])  for i, k in enumerate(keys)},
        "total_order": {k: float(STi[i]) for i, k in enumerate(keys)},
        "varY": varY
    }