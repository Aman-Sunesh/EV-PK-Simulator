# dosing_program.py
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Expand high-level dosing “program” steps into the low-level
# simulator-friendly `dosing` list:
#     [{time: float, dose: float, Tinf?: float}, ...]
#
# Supports step types:
#  • bolus      → single IV bolus at an absolute time
#  • infusion   → single infusion window (dose is total over Tinf)
#  • repeat     → repeated bolus/infusion on a fixed schedule
#  • titrate    → stepwise dose adjustments every τ (optional per-step Tinf)
#  • onoff      → infusion on/off windows across a duration (window=Tinf=dose_on)
#
# Examples:
#  {"type":"bolus","time":0,"dose":100}
#  {"type":"infusion","start":0,"dose":200,"Tinf":1.0}
#  {"type":"repeat","pattern":"bolus","start":0,"tau":8,"count":6,"dose":100}
#  {"type":"repeat","pattern":"infusion","start":0,"tau":24,"count":5,"dose":2400,"Tinf":8}
#  {"type":"titrate","start":0,"tau":24,"steps":[{"dose":200},{"dose":150},{"dose":100}]}
#  {"type":"onoff","start":0,"duration":72,"dose":2400,"dose_on":8,"dose_off":16}
#
# Notes:
#  • For “infusion” (and repeat: infusion), `dose` is the total amount delivered over Tinf.
#  • “onoff” expands to infusion windows: period = dose_on + dose_off, window Tinf = dose_on.
#  • Minimal validation enforces positivity for key fields (dose, Tinf, tau, count, etc.).
#  • `route` is accepted for symmetry with other APIs; current logic is route-agnostic.
# ─────────────────────────────────────────────────────────────────────────────────────────────────

from typing import List, Dict, Optional

def _pos(name, v):
    if v is None or v <= 0:
        raise ValueError(f"'{name}' must be > 0")

def expand_program(program: List[Dict], route: str, default_Tinf: Optional[float]=None) -> List[Dict]:
    """
    Convert a high-level dosing program into the 'dosing' list the simulators use:
      [{time: float, dose: float, Tinf?: float}, ...]

    Supported steps (examples):
      {"type":"bolus","time":0,"dose":100}
      {"type":"infusion","start":0,"dose":200,"Tinf":1.0}
      {"type":"repeat","pattern":"bolus","start":0,"tau":8,"count":6,"dose":100}
      {"type":"repeat","pattern":"infusion","start":0,"tau":24,"count":5,"dose":2400,"Tinf":8}
      {"type":"titrate","start":0,"tau":24,"steps":[{"dose":200},{"dose":150},{"dose":100}]}
      {"type":"onoff","start":0,"duration":72,"dose":2400,"dose_on":8,"dose_off":16}  # infusion on/off windows
    Notes:
      • For 'infusion' and 'repeat: infusion', 'dose' is the total amount delivered over Tinf.
      • 'onoff' expands to a sequence of infusion windows: repeated (dose_on+dose_off) with per-window Tinf=dose_on.
    """
    dosing: List[Dict] = []
    r = route.lower()

    for step in (program or []):
        t = step.get("type","").lower()

        if t == "bolus":
            ti = float(step["time"]); d = float(step["dose"]); _pos("dose", d)
            dosing.append({"time": ti, "dose": d})

        elif t == "infusion":
            st = float(step["start"]); d = float(step["dose"]); Tinf = float(step.get("Tinf", default_Tinf or 0.0))
            _pos("dose", d); _pos("Tinf", Tinf)
            dosing.append({"time": st, "dose": d, "Tinf": Tinf})

        elif t == "repeat":
            pat = step.get("pattern","bolus").lower()
            start = float(step.get("start", 0.0))
            tau   = float(step["tau"]); _pos("tau", tau)
            cnt   = int(step["count"]); _pos("count", cnt)
            d     = float(step["dose"]); _pos("dose", d)

            if pat == "bolus":
                for i in range(cnt):
                    dosing.append({"time": start + i*tau, "dose": d})

            elif pat == "infusion":
                Tinf = float(step.get("Tinf", default_Tinf or 0.0)); _pos("Tinf", Tinf)
                for i in range(cnt):
                    dosing.append({"time": start + i*tau, "dose": d, "Tinf": Tinf})

            else:
                raise ValueError("repeat.pattern must be 'bolus' or 'infusion'")

        elif t == "titrate":
            start = float(step.get("start", 0.0))
            tau   = float(step["tau"]); _pos("tau", tau)
            steps = step["steps"]; 

            for i, s in enumerate(steps):
                d = float(s["dose"]); _pos("dose", d)
                Tinf = step.get("Tinf") if "Tinf" in step else s.get("Tinf", None)
                ti = start + i*tau
                dosing.append({"time": ti, "dose": d, **({"Tinf": float(Tinf)} if Tinf else {})})

        elif t == "onoff":
            # infusion windows: on for dose_on, off for dose_off, within total 'duration'
            start = float(step.get("start", 0.0))
            dur   = float(step["duration"]); _pos("duration", dur)
            dose_on  = float(step["dose_on"]);  _pos("dose_on", dose_on)
            dose_off = float(step.get("dose_off", 0.0))
            d = float(step["dose"]); _pos("dose", d)
            # use per-window dose proportional to on-time if caller gave a per-day/total figure
            # dose is per-window.
            tcur = start; end = start + dur
            while tcur < end:
                dosing.append({"time": tcur, "dose": d, "Tinf": dose_on})
                tcur += dose_on + dose_off

        else:
            raise ValueError(f"Unknown program step type: {step.get('type')}")

    return dosing
