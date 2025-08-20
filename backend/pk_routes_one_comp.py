# pk_routes_one_comp.py
#
# ────────────────────────────────────────────────────────────────────────────────────────
# EV–PK Simulator — One-Compartment Route Simulator (IV bolus / infusion / oral / SC)
#
# What this module provides
#  • simulate_one_comp_route(route, params, dosing|repeat, t_end, dt) → dict
#      - Supports: "iv_bolus", "iv_infusion", "oral", "sc"
#      - Accepts either an explicit `dosing` list or a simple `repeat` rule
#      - Returns time/conc arrays, summary KPIs (Cmax, Tmax, AUC), and dosing echo
#
#  • Internal helpers (kept stable — used by tests & other modules)
#      _time_grid, _trapz, _expm1_pos, _validate_positive, _validate_nonnegative,
#      _expand_extravascular_continuous, _iv_bolus_curve, _iv_infusion_curve,
#      _extravascular_curve, _summarize
#
# Notes
#  • Parameter expectations:
#      - Common: Vd > 0, kel > 0
#      - IV infusion: Tinf > 0 (per event or params["Tinf"])
#      - Oral/SC: F ≥ 0, ka > 0; when an event has Tinf, it is expanded as micro-boluses
#  • For `repeat`, steady-state summaries are returned when formulas are applicable.
#  • Behavior is deterministic and vectorized; no random state used.
# ────────────────────────────────────────────────────────────────────────────────────────

import numpy as np
from typing import List, Dict, Optional

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

def _expand_extravascular_continuous(
    dosing: List[Dict],
    dt: float,
    max_pulses: int = 2000
) -> List[Dict]:
    """
    For oral/sc events that include Tinf (an 'on' window), split the total dose
    evenly into many small boluses across the window to approximate continuous input.
    """
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
            # no window → single bolus
            ev2 = dict(ev); ev2.pop("Tinf", None)  # tidy
            out.append(ev2)
    return out

# Core equations (one compartment) 
def _iv_bolus_curve(t: np.ndarray, Vd: float, kel: float,
                    doses: List[Dict]) -> np.ndarray:
    C = np.zeros_like(t, dtype=float)
    for d in doses:
        ti = float(d["time"])
        Di = float(d["dose"])
        mask = t >= ti
        C[mask] += (Di / Vd) * np.exp(-kel * (t[mask] - ti))
    return C

def _iv_infusion_curve(t: np.ndarray, Vd: float, kel: float,
                       doses: List[Dict], Tinf_default: Optional[float]) -> np.ndarray:
    # CL = kel * Vd, K0 = D / Tinf
    CL = kel * Vd
    C = np.zeros_like(t, dtype=float)
    for d in doses:
        ti = float(d["time"])
        Di = float(d["dose"])
        Tinf = float(d.get("Tinf", Tinf_default or 0.0))
        _validate_positive("Tinf", Tinf)
        K0 = Di / Tinf

        # during infusion
        during = (t >= ti) & (t <= ti + Tinf)
        if np.any(during):
            td = t[during] - ti
            C[during] += (K0 / CL) * _expm1_pos(kel * td)

        # after infusion
        after = t > (ti + Tinf)
        if np.any(after):
            ta = t[after] - (ti + Tinf)
            C_end = (K0 / CL) * _expm1_pos(kel * Tinf)
            C[after] += C_end * np.exp(-kel * ta)

    return C

def _extravascular_curve(t: np.ndarray, Vd: float, kel: float,
                         doses: List[Dict], F: float, ka: float) -> np.ndarray:
    _validate_nonnegative("F", F)
    _validate_positive("ka", ka)
    C = np.zeros_like(t, dtype=float)
    same = np.isclose(ka, kel)

    for d in doses:
        ti = float(d["time"])
        Di = float(d["dose"])
        mask = t >= ti
        tm = t[mask] - ti

        if same:
            # limit as ka -> kel: (F*D/Vd) * ka * (t-ti) * exp(-ka (t-ti))
            C[mask] += (F * Di / Vd) * ka * tm * np.exp(-ka * tm)
        else:
            coeff = (F * Di / Vd) * (ka / (ka - kel))
            C[mask] += coeff * (np.exp(-kel * tm) - np.exp(-ka * tm))

    return C

def _summarize(t: np.ndarray, C: np.ndarray) -> Dict[str, float]:
    idx = int(np.argmax(C))
    Cmax = float(C[idx])
    Tmax = float(t[idx])
    AUC  = _trapz(t, C)
    return {"Cmax": Cmax, "Tmax": Tmax, "AUC": AUC}

def simulate_one_comp_route(
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

    # validate core params
    Vd  = float(params.get("Vd", 0.0))
    kel = float(params.get("kel", 0.0))
    _validate_positive("Vd", Vd)
    _validate_positive("kel", kel)

    # build time grid
    t = _time_grid(t_end, dt)

    # if repeat rule provided, synthesize dosing list
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

    # If extravascular, expand any Tinf windows into micro-boluses
    if route in ("oral", "sc"):
        dosing = _expand_extravascular_continuous(dosing, dt)

    if route == "iv_bolus":
        C = _iv_bolus_curve(t, Vd, kel, dosing)

    elif route == "iv_infusion":
        Tinf_default = params.get("Tinf", None)
        C = _iv_infusion_curve(t, Vd, kel, dosing, Tinf_default)

    elif route == "oral":
        F  = float(params.get("F", 1.0))
        ka = float(params.get("ka", 0.0))
        _validate_positive("ka", ka)
        C = _extravascular_curve(t, Vd, kel, dosing, F, ka)

    elif route == "sc":
        F  = float(params.get("F", 1.0))
        ka = float(params.get("ka", 0.0))
        _validate_positive("ka", ka)
        C = _extravascular_curve(t, Vd, kel, dosing, F, ka)

    else:
        raise ValueError("route must be one of: iv_bolus, iv_infusion, oral, sc")

    summary = _summarize(t, C)

    # If this was a repeat rule with constant tau & Tinf (infusion), also return steady-state Cmax/Cmin
    extras = {}
    if repeat is not None:
        tau = float(repeat.get("tau", 0.0))
        if tau > 0:
            if route == "iv_bolus":
                # Cmax_ss = (D/Vd) / (1 - e^{-kel tau})
                D = float(repeat.get("dose", 0.0))
                extras["Cmax_ss"] = float((D / Vd) / (1.0 - np.exp(-kel * tau)))
                extras["Cmin_ss"] = float(extras["Cmax_ss"] * np.exp(-kel * tau))
            elif route == "iv_infusion":
                # Cmax_ss = (K0/CL) * (1 - e^{-kel Tinf}) / (1 - e^{-kel tau})
                Tinf = float(repeat.get("Tinf", params.get("Tinf", 0.0)))
                D    = float(repeat.get("dose", 0.0))
                CL   = kel * Vd
                _validate_positive("Tinf", Tinf)

                if tau < Tinf:
                    extras["warning"] = (
                        "tau < Tinf → overlapping infusions: steady-state Cmax/Cmin "
                        "formulas are not applicable; omitted."
                    )
                else:
                    K0   = D / Tinf
                    cmax_ss = (K0 / CL) * _expm1_pos(kel * Tinf) / (1.0 - np.exp(-kel * tau))
                    cmin_ss = cmax_ss * np.exp(-kel * (tau - Tinf))
                    extras["Cmax_ss"] = float(cmax_ss)
                    extras["Cmin_ss"] = float(cmin_ss)
                    
            elif route in ("oral", "sc"):
                # Average Css = (F*D)/(CL * tau), but peaks/troughs depend on ka.
                D  = float(repeat.get("dose", 0.0))
                F  = float(params.get("F", 1.0))
                CL = kel * Vd
                extras["Cavg_ss"] = float((F * D) / (CL * tau))

    out = {
        "time": t.tolist(),
        "conc": C.tolist(),
        "summary": {**summary, **extras},
        "dosing": dosing
    }

    return out
