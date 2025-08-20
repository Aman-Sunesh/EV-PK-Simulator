# pk_routes_two_comp.py
#
# ───────────────────────────────────────────────────────────────────────────────────────────
# EV–PK Simulator — Two-Compartment Route Simulator
# (IV bolus / short infusion / oral / subcutaneous)
#
# What this module provides
#  • simulate_two_comp_route(route, params, dosing|repeat, t_end, dt) → dict
#      - Routes: "iv_bolus", "iv_infusion", "oral", "sc"
#      - Params may be given as macro (A, α, B, β) or micro (k10, k12, k21, V1)
#      - Accepts either explicit `dosing` list or simple `repeat` rule
#      - Returns time/conc arrays, summary KPIs (Cmax, Tmax, AUC), and dosing echo
#
#  • Internal helpers (used by tests/other modules)
#      _time_grid, _trapz, _expm1_pos,
#      _validate_positive, _validate_nonnegative,
#      _macros_from_micro, _get_macros,
#      _expand_extravascular_continuous,
#      _iv_bolus_curve_two, _iv_infusion_curve_two, _phi, _extravascular_curve_two,
#      _summarize
#
# Notes
#  • Macro form models concentration per administered dose D:
#       C(t) = Σ_i D_i [ A e^(−α (t−t_i)) + B e^(−β (t−t_i)) ] for t ≥ t_i
#    When using micro constants, we convert (k10,k12,k21,V1) → (A,α,B,β).
#  • “Oral/SC” here means first-order absorption into the central compartment
#    (Bateman-style convolution against the two-exponential impulse response).
#  • For `repeat` with constant τ, steady-state summaries are returned where valid.
# ───────────────────────────────────────────────────────────────────────────────────────────

import numpy as np
from typing import List, Dict, Optional, Tuple

def _time_grid(t_end: float, dt: float) -> np.ndarray:
    n = int(np.floor(t_end / dt)) + 1
    return np.linspace(0.0, t_end, n)

def _trapz(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.trapz(y, x))

def _expm1_pos(x: np.ndarray) -> np.ndarray:
    # stable 1 - exp(-x)
    return -np.expm1(-x)

def _validate_positive(name: str, val: float):
    if val is None or val <= 0:
        raise ValueError(f"'{name}' must be > 0")

def _validate_nonnegative(name: str, val: float):
    if val is None or val < 0:
        raise ValueError(f"'{name}' must be ≥ 0")

def _macros_from_micro(k10: float, k12: float, k21: float, V1: float
                      ) -> Tuple[float, float, float, float]:
    """
    Compute (A, alpha, B, beta) from micro-constants (k10, k12, k21, V1).
    alpha, beta are the positive roots; A,B are per-unit-dose coefficients
    for C(t) = D*(A*e^{-alpha t} + B*e^{-beta t}).
    """
    _validate_positive("k10", k10)
    _validate_positive("k12", k12)
    _validate_positive("k21", k21)
    _validate_positive("V1",  V1)

    s = k12 + k21 + k10
    disc = s*s - 4.0*k21*k10

    if disc < 0:  # numerical clamp
        disc = 0.0

    root = np.sqrt(disc)
    alpha = 0.5*(s + root)
    beta  = 0.5*(s - root)

    # ensure alpha >= beta
    if beta <= 0 or alpha <= 0:
        raise ValueError("Computed non-positive macro rates from micro-constants.")
    if beta > alpha:
        alpha, beta = beta, alpha

    den = alpha - beta
    if den == 0:
        raise ValueError("alpha == beta (degenerate), cannot form distinct macro-exponentials.")

    # Standard macro coefficients per unit dose
    A = (alpha - k21) / (V1 * den)
    B = (k21 - beta)  / (V1 * den)

    return A, alpha, B, beta

def _get_macros(params: Dict) -> Tuple[float, float, float, float]:
    """
    Resolve (A, alpha, B, beta) either directly from params (macro form),
    or derive from micro-constants (k10,k12,k21,V1).
    """
    if all(k in params for k in ("A","alpha","B","beta")):
        A     = float(params["A"])
        alpha = float(params["alpha"])
        B     = float(params["B"])
        beta  = float(params["beta"])

        for n,v in (("A",A),("alpha",alpha),("B",B),("beta",beta)):
            _validate_nonnegative(n, v)  # allow zeros but not negative
        _validate_positive("alpha", alpha)
        _validate_positive("beta",  beta)

        if not (alpha > 0 and beta > 0):
            raise ValueError("alpha and beta must be > 0")

        if np.isclose(alpha, beta):
            raise ValueError("alpha and beta too close; need distinct exponentials.")

        return A, alpha, B, beta

    # else try micro
    needed = ("k10","k12","k21","V1")

    if not all(k in params for k in needed):
        raise ValueError("Provide either macro params (A,alpha,B,beta) "
                         "or micro params (k10,k12,k21,V1).")

    return _macros_from_micro(
        float(params["k10"]),
        float(params["k12"]),
        float(params["k21"]),
        float(params["V1"])
    )

def _expand_extravascular_continuous(
    dosing: List[Dict], dt: float, max_pulses: int = 2000
) -> List[Dict]:
    out: List[Dict] = []
    for ev in dosing or []:
        Tinf = float(ev.get("Tinf") or 0.0)
        if Tinf > 0:
            D = float(ev["dose"])
            n = int(np.ceil(Tinf / max(dt, 1e-12)))
            n = max(1, min(max_pulses, n))
            delta = Tinf / n
            d_micro = D / n
            t0 = float(ev["time"])
            for j in range(n):
                out.append({"time": t0 + j*delta, "dose": d_micro})
        else:
            ev2 = dict(ev); ev2.pop("Tinf", None)
            out.append(ev2)
    return out


# ---------------------------------------------------------------------------
# Core route curves (two compartment, linear)
#   All use superposition across 'doses' list with entries {time, dose, (Tinf?)}
# ---------------------------------------------------------------------------
def _iv_bolus_curve_two(t: np.ndarray,
                        A: float, alpha: float,
                        B: float, beta: float,
                        doses: List[Dict]) -> np.ndarray:
    """
    C(t) = sum_i D_i * [ A e^{-alpha (t - t_i)} + B e^{-beta (t - t_i)} ]  for t >= t_i
    """
    C = np.zeros_like(t, dtype=float)
    for d in doses:
        ti = float(d["time"])
        Di = float(d["dose"])
        mask = t >= ti
        if np.any(mask):
            dt = t[mask] - ti
            C[mask] += Di * (A*np.exp(-alpha*dt) + B*np.exp(-beta*dt))
    return C

def _iv_infusion_curve_two(t: np.ndarray,
                           A: float, alpha: float,
                           B: float, beta: float,
                           doses: List[Dict],
                           Tinf_default: Optional[float]) -> np.ndarray:
    """
    Short-term infusion, per dose i:
      K0 = D_i / Tinf
      During (u = t - t_i, 0 ≤ u ≤ Tinf):
         C_i = K0 * [ A/alpha * (1 - e^{-alpha u}) + B/beta * (1 - e^{-beta u}) ]
      After (u > Tinf):
         C_i = K0 * [ A/alpha * (1 - e^{-alpha Tinf}) * e^{-alpha (u - Tinf)}
                    + B/beta  * (1 - e^{-beta  Tinf}) * e^{-beta  (u - Tinf)} ]
    """
    _validate_positive("alpha", alpha)
    _validate_positive("beta",  beta)
    C = np.zeros_like(t, dtype=float)
    inv_alpha = 1.0/alpha
    inv_beta  = 1.0/beta
    for d in doses:
        ti = float(d["time"])
        Di = float(d["dose"])
        Tinf = float(d.get("Tinf", Tinf_default or 0.0))
        _validate_positive("Tinf", Tinf)
        K0 = Di / Tinf

        during = (t >= ti) & (t <= ti + Tinf)
        if np.any(during):
            u = t[during] - ti
            C[during] += K0 * ( A*inv_alpha*_expm1_pos(alpha*u)
                               + B*inv_beta *_expm1_pos(beta *u) )

        after = t > (ti + Tinf)
        if np.any(after):
            u = t[after] - (ti + Tinf)
            Aend = A*inv_alpha*_expm1_pos(alpha*Tinf)
            Bend = B*inv_beta *_expm1_pos(beta *Tinf)
            C[after] += K0 * ( Aend*np.exp(-alpha*u) + Bend*np.exp(-beta*u) )
    return C

def _phi(delta: np.ndarray, rate: float, ka: float) -> np.ndarray:
    """
    Helper for first-order absorption convolution term:
      ka/(rate - ka) * (e^{-ka Δ} - e^{-rate Δ})
    with a numerically stable limit when rate ≈ ka:
      → ka * Δ * e^{-ka Δ}
    """
    rate = float(rate); ka = float(ka)
    out = np.empty_like(delta, dtype=float)
    diff = rate - ka
    close = np.isclose(diff, 0.0)

    if np.any(~close):
        d = delta[~close]
        out[~close] = (ka/diff) * (np.exp(-ka*d) - np.exp(-rate*d))

    if np.any(close):
        d = delta[close]
        out[close] = ka * d * np.exp(-ka*d)

    return out

def _extravascular_curve_two(t: np.ndarray,
                             A: float, alpha: float,
                             B: float, beta: float,
                             doses: List[Dict], F: float, ka: float) -> np.ndarray:
    """
    First-order absorption into a linear 2-comp system (central input).
    Convolution of input rate F*D*ka*e^{-ka (t-ti)} with IV-bolus impulse response
    h(u) = A e^{-alpha u} + B e^{-beta u}, u≥0:
      C_i(t) = F*D * [ A * φ(Δ, alpha, ka) + B * φ(Δ, beta, ka) ],
      where φ(Δ, r, ka) = ka/(r - ka) * (e^{-ka Δ} - e^{-r Δ})
      (stable limit φ → ka*Δ*e^{-ka Δ} when r ≈ ka)
    """
    _validate_nonnegative("F", F)
    _validate_positive("ka", ka)
    C = np.zeros_like(t, dtype=float)
    for d in doses:
        ti = float(d["time"])
        Di = float(d["dose"])
        mask = t >= ti
        if np.any(mask):
            dt = t[mask] - ti
            C[mask] += F*Di * ( A*_phi(dt, alpha, ka) + B*_phi(dt, beta, ka) )

    return C

def _summarize(t: np.ndarray, C: np.ndarray) -> Dict[str, float]:
    idx = int(np.argmax(C))
    Cmax = float(C[idx])
    Tmax = float(t[idx])
    AUC  = _trapz(t, C)
    return {"Cmax": Cmax, "Tmax": Tmax, "AUC": AUC}

def simulate_two_comp_route(
    route: str,
    params: Dict,
    dosing: Optional[List[Dict]],
    repeat: Optional[Dict],
    t_end: float,
    dt: float
) -> Dict:
    # basic grid checks
    if dt <= 0:
        raise ValueError("'dt' must be > 0")
    if t_end < 0:
        raise ValueError("'t_end' must be ≥ 0")

    route = route.lower()

    # resolve macro parameters
    A, alpha, B, beta = _get_macros(params)

    # build time grid
    t = _time_grid(t_end, dt)

    # synthesize dosing if repeat rule provided
    if dosing is None and repeat is not None:
        start = float(repeat.get("start", 0.0))
        tau   = float(repeat.get("tau", 0.0))
        count = int(repeat.get("count", 0))
        dose0 = float(repeat.get("dose", 0.0))
        _validate_positive("tau", tau)
        _validate_positive("dose", dose0)
        _validate_positive("count", count)
        dosing = []

        for i in range(count):
            entry = {"time": start + i * tau, "dose": dose0}

            if route in ("iv_infusion", "oral", "sc"):
                Tinf = float(repeat.get("Tinf", params.get("Tinf", 0.0)))
                if Tinf > 0:
                    _validate_positive("Tinf", Tinf)
                    entry["Tinf"] = Tinf
            dosing.append(entry)

    if not dosing:
        raise ValueError("Provide 'dosing' list or 'repeat' rule.")

    # For oral/sc, approximate continuous on-window as micro-boluses
    if route in ("oral", "sc"):
        dosing = _expand_extravascular_continuous(dosing, dt)

    # compute curve by route
    if route == "iv_bolus":
        C = _iv_bolus_curve_two(t, A, alpha, B, beta, dosing)

    elif route == "iv_infusion":
        Tinf_default = params.get("Tinf", None)
        C = _iv_infusion_curve_two(t, A, alpha, B, beta, dosing, Tinf_default)

    elif route in ("oral", "sc"):
        F  = float(params.get("F", 1.0))
        ka = float(params.get("ka", 0.0))
        _validate_positive("ka", ka)
        C = _extravascular_curve_two(t, A, alpha, B, beta, dosing, F, ka)

    else:
        raise ValueError("route must be one of: iv_bolus, iv_infusion, oral, sc")

    summary = _summarize(t, C)

    # Steady-state style KPIs for simple repeats (constant tau)
    extras = {}
    if repeat is not None:
        tau = float(repeat.get("tau", 0.0))
        if tau > 0:
            if route == "iv_bolus":
                # Cmax_ss = D*(A/(1-e^{-alpha tau}) + B/(1-e^{-beta tau}))
                # Cmin_ss = D*(A*e^{-alpha tau}/(1-e^{-alpha tau}) + B*e^{-beta tau}/(1-e^{-beta tau}))
                D = float(repeat.get("dose", 0.0))
                one_ma = 1.0 - np.exp(-alpha*tau)
                one_mb = 1.0 - np.exp(-beta *tau)
                cmax_ss = D * ( A/one_ma + B/one_mb )
                cmin_ss = D * ( A*np.exp(-alpha*tau)/one_ma + B*np.exp(-beta*tau)/one_mb )
                extras["Cmax_ss"] = float(cmax_ss)
                extras["Cmin_ss"] = float(cmin_ss)

            elif route == "iv_infusion":
                # Non-overlap assumption tau ≥ Tinf; otherwise skip KPIs and warn.
                Tinf = float(repeat.get("Tinf", params.get("Tinf", 0.0)))
                _validate_positive("Tinf", Tinf)
                if tau < Tinf:
                    extras["warning"] = (
                        "tau < Tinf → overlapping infusions: steady-state Cmax/Cmin "
                        "formulas are not applicable; omitted."
                    )
                else:
                    D  = float(repeat.get("dose", 0.0))
                    K0 = D / Tinf
                    one_ma = 1.0 - np.exp(-alpha*tau)
                    one_mb = 1.0 - np.exp(-beta *tau)

                    # PFIM 1.2.2.2 steady-state form (end of infusion is peak)
                    Aend = (A/alpha) * _expm1_pos(alpha*Tinf)
                    Bend = (B/beta)  * _expm1_pos(beta *Tinf)
                    cmax_ss = K0 * ( Aend/one_ma + Bend/one_mb )
                    cmin_ss = K0 * ( Aend*np.exp(-alpha*(tau - Tinf))/one_ma
                                    + Bend*np.exp(-beta *(tau - Tinf))/one_mb )
                    extras["Cmax_ss"] = float(cmax_ss)
                    extras["Cmin_ss"] = float(cmin_ss)

            elif route in ("oral", "sc"):
                # Css,avg = (F*D)/(CL * tau), with CL = 1 / (A/alpha + B/beta)
                D  = float(repeat.get("dose", 0.0))
                F  = float(params.get("F", 1.0))
                inv_CL = (A/alpha + B/beta)

                if inv_CL <= 0:
                    # Should not happen for positive macros, but guard anyway
                    pass
                else:
                    extras["Cavg_ss"] = float( (F * D * inv_CL) / tau )

    out = {
        "time": t.tolist(),
        "conc": C.tolist(),
        "summary": {**summary, **extras},
        "dosing": dosing
    }
    
    return out
