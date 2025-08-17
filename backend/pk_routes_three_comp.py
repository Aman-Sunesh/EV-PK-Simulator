import numpy as np
from typing import List, Dict, Optional, Tuple


def _time_grid(t_end: float, dt: float) -> np.ndarray:
    n = int(np.floor(t_end / dt)) + 1
    return np.linspace(0.0, t_end, n)


def _trapz(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.trapz(y, x))


def _expm1_pos(x: np.ndarray) -> np.ndarray:
    return -np.expm1(-x)


def _validate_positive(name: str, val: float):
    if val is None or val <= 0:
        raise ValueError(f"'{name}' must be > 0")


def _validate_nonnegative(name: str, val: float):
    if val is None or val < 0:
        raise ValueError(f"'{name}' must be ≥ 0")


# ---------- macros from micro via eigendecomposition ----------
def _macros_from_micro_eig(
    k10: float, k12: float, k13: float, k21: float, k31: float, V1: float
) -> Tuple[float, float, float, float, float, float]:
    for n, v in (("k10", k10), ("k12", k12), ("k13", k13),
                 ("k21", k21), ("k31", k31), ("V1", V1)):
        _validate_positive(n, v)

    M = np.array([
        [-(k10 + k12 + k13),  k21,               k31            ],
        [ k12,               -k21,               0.0            ],
        [ k13,                0.0,              -k31            ],
    ], dtype=float)

    w, V = np.linalg.eig(M)
    w = np.real(w); V = np.real(V)  # guard tiny imaginary parts
    rates = -w
    if not np.all(rates > 0):
        raise ValueError("Non-positive macro rates derived; check micro parameters.")

    e1 = np.array([1.0, 0.0, 0.0])
    u  = np.linalg.solve(V, e1)     # V^{-1} e1
    wrow = V[0, :]                  # e1^T V
    coefs = (wrow * u) / V1         # per-unit-dose A,B,C in 1/V1 units

    order = np.argsort(rates)[::-1]  # α≥β≥γ
    alpha, beta, gamma = rates[order]
    A, B, C = coefs[order]
    return float(A), float(alpha), float(B), float(beta), float(C), float(gamma)


def _get_macros(params: Dict) -> Tuple[float, float, float, float, float, float]:
    if all(k in params for k in ("A","alpha","B","beta","C","gamma")):
        A = float(params["A"]);     alpha = float(params["alpha"])
        B = float(params["B"]);     beta  = float(params["beta"])
        C = float(params["C"]);     gamma = float(params["gamma"])
        for n, v in (("alpha", alpha), ("beta", beta), ("gamma", gamma)):
            _validate_positive(n, v)
        for n, v in (("A", A), ("B", B), ("C", C)):
            _validate_nonnegative(n, v)
        # require separation to avoid degeneracy
        if min(abs(alpha-beta), abs(alpha-gamma), abs(beta-gamma)) < 1e-6*max(alpha, beta, gamma):
            raise ValueError("Macro rates too close; need distinct exponentials.")
        return A, alpha, B, beta, C, gamma

    needed = ("k10","k12","k13","k21","k31","V1")
    if not all(k in params for k in needed):
        raise ValueError("Provide either macros (A,alpha,B,beta,C,gamma) "
                         "or micros (k10,k12,k13,k21,k31,V1).")
    return _macros_from_micro_eig(
        float(params["k10"]), float(params["k12"]), float(params["k13"]),
        float(params["k21"]), float(params["k31"]), float(params["V1"])
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


# ---------- route curves ----------
def _iv_bolus_curve_three(t: np.ndarray,
                          A: float, alpha: float,
                          B: float, beta: float,
                          C: float, gamma: float,
                          doses: List[Dict]) -> np.ndarray:
    Cc = np.zeros_like(t, dtype=float)
    for d in doses:
        ti = float(d["time"]); Di = float(d["dose"])
        mask = t >= ti
        if np.any(mask):
            dt = t[mask] - ti
            Cc[mask] += Di * (A*np.exp(-alpha*dt) + B*np.exp(-beta*dt) + C*np.exp(-gamma*dt))
    return Cc


def _iv_infusion_curve_three(t: np.ndarray,
                             A: float, alpha: float,
                             B: float, beta: float,
                             C: float, gamma: float,
                             doses: List[Dict],
                             Tinf_default: Optional[float]) -> np.ndarray:
    Cc = np.zeros_like(t, dtype=float)
    inv_alpha = 1.0/alpha; inv_beta = 1.0/beta; inv_gamma = 1.0/gamma

    for d in doses:
        ti = float(d["time"]); Di = float(d["dose"])
        Tinf = float(d.get("Tinf", Tinf_default or 0.0))
        _validate_positive("Tinf", Tinf)
        K0 = Di / Tinf

        during = (t >= ti) & (t <= ti + Tinf)
        if np.any(during):
            u = t[during] - ti
            Cc[during] += K0 * (
                A*inv_alpha*_expm1_pos(alpha*u) +
                B*inv_beta *_expm1_pos(beta *u) +
                C*inv_gamma*_expm1_pos(gamma*u)
            )

        after = t > (ti + Tinf)
        if np.any(after):
            u = t[after] - (ti + Tinf)
            Aend = A*inv_alpha*_expm1_pos(alpha*Tinf)
            Bend = B*inv_beta *_expm1_pos(beta *Tinf)
            Cend = C*inv_gamma*_expm1_pos(gamma*Tinf)
            Cc[after] += K0 * (Aend*np.exp(-alpha*u) + Bend*np.exp(-beta*u) + Cend*np.exp(-gamma*u))
    return Cc


def _phi(delta: np.ndarray, rate: float, ka: float) -> np.ndarray:
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


def _extravascular_curve_three(t: np.ndarray,
                               A: float, alpha: float,
                               B: float, beta: float,
                               C: float, gamma: float,
                               doses: List[Dict], F: float, ka: float) -> np.ndarray:
    _validate_nonnegative("F", F)
    _validate_positive("ka", ka)
    Cc = np.zeros_like(t, dtype=float)
    for d in doses:
        ti = float(d["time"]); Di = float(d["dose"])
        mask = t >= ti
        if np.any(mask):
            dt = t[mask] - ti
            Cc[mask] += F*Di * (
                A*_phi(dt, alpha, ka) +
                B*_phi(dt, beta,  ka) +
                C*_phi(dt, gamma, ka)
            )
    return Cc


def _summarize(t: np.ndarray, conc: np.ndarray) -> Dict[str, float]:
    idx = int(np.argmax(conc))
    return {"Cmax": float(conc[idx]), "Tmax": float(t[idx]), "AUC": _trapz(t, conc)}


def simulate_three_comp_route(
    route: str,
    params: Dict,
    dosing: Optional[List[Dict]],
    repeat: Optional[Dict],
    t_end: float,
    dt: float
) -> Dict:
    if dt <= 0:  raise ValueError("'dt' must be > 0")
    if t_end < 0: raise ValueError("'t_end' must be ≥ 0")

    route = route.lower()

    A, alpha, B, beta, C, gamma = _get_macros(params)
    t = _time_grid(t_end, dt)

    if dosing is None and repeat is not None:
        start = float(repeat.get("start", 0.0))
        tau   = float(repeat.get("tau", 0.0)); _validate_positive("tau", tau)
        count = int(repeat.get("count", 0));   _validate_positive("count", count)
        dose0 = float(repeat.get("dose", 0.0));_validate_positive("dose", dose0)
        dosing = []
        for i in range(count):
            entry = {"time": start + i*tau, "dose": dose0}
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

    if route == "iv_bolus":
        conc = _iv_bolus_curve_three(t, A, alpha, B, beta, C, gamma, dosing)
    elif route == "iv_infusion":
        Tinf_default = params.get("Tinf", None)
        conc = _iv_infusion_curve_three(t, A, alpha, B, beta, C, gamma, dosing, Tinf_default)
    elif route in ("oral", "sc"):
        F  = float(params.get("F", 1.0))
        ka = float(params.get("ka", 0.0))
        _validate_positive("ka", ka)
        conc = _extravascular_curve_three(t, A, alpha, B, beta, C, gamma, dosing, F, ka)
    else:
        raise ValueError("route must be one of: iv_bolus, iv_infusion, oral, sc")

    summary = _summarize(t, conc)

    # Steady-state style KPIs for simple repeats (constant tau), mirroring 1c/2c
    extras: Dict[str, float] = {}
    if repeat is not None:
        tau = float(repeat.get("tau", 0.0))
        if tau > 0:
            if route == "iv_bolus":
                # Cmax_ss = D * ( A/(1-e^{-ατ}) + B/(1-e^{-βτ}) + C/(1-e^{-γτ}) )
                # Cmin_ss = Cmax_ss * exp(-rates*τ) componentwise and summed
                D = float(repeat.get("dose", 0.0))
                one_ma = 1.0 - np.exp(-alpha*tau)
                one_mb = 1.0 - np.exp(-beta *tau)
                one_mg = 1.0 - np.exp(-gamma*tau)
                cmax_ss = D * ( A/one_ma + B/one_mb + C/one_mg )
                cmin_ss = D * ( A*np.exp(-alpha*tau)/one_ma
                               + B*np.exp(-beta *tau)/one_mb
                               + C*np.exp(-gamma*tau)/one_mg )
                extras["Cmax_ss"] = float(cmax_ss)
                extras["Cmin_ss"] = float(cmin_ss)

            elif route == "iv_infusion":
                # Assume non-overlap tau ≥ Tinf; otherwise warn & skip
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
                    one_mg = 1.0 - np.exp(-gamma*tau)
                    Aend = (A/alpha) * _expm1_pos(alpha*Tinf)
                    Bend = (B/beta)  * _expm1_pos(beta *Tinf)
                    Cend = (C/gamma) * _expm1_pos(gamma*Tinf)
                    cmax_ss = K0 * ( Aend/one_ma + Bend/one_mb + Cend/one_mg )
                    cmin_ss = K0 * (
                        Aend*np.exp(-alpha*(tau - Tinf))/one_ma
                      + Bend*np.exp(-beta *(tau - Tinf))/one_mb
                      + Cend*np.exp(-gamma*(tau - Tinf))/one_mg
                    )
                    extras["Cmax_ss"] = float(cmax_ss)
                    extras["Cmin_ss"] = float(cmin_ss)

            elif route in ("oral", "sc"):
                # Css,avg = (F*D)/(CL * tau), with 1/CL = A/α + B/β + C/γ
                D  = float(repeat.get("dose", 0.0))
                Fp = float(params.get("F", 1.0))
                inv_CL = (A/alpha + B/beta + C/gamma)
                if inv_CL > 0:
                    extras["Cavg_ss"] = float( (Fp * D * inv_CL) / tau )

    out = {
        "time": t.tolist(),
        "conc": conc.tolist(),
        "summary": {**summary, **extras},
        "dosing": dosing
    }

    return out