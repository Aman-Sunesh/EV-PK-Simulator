# dosing_program.py
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Expand high-level dosing “program” steps into the low-level simulator-friendly
# `dosing` list:
#     [{time: float, dose: float, Tinf?: float}, ...]
#
# Supports step types:
#  • bolus      → single IV bolus at an absolute time
#  • infusion   → single infusion window (dose is total over Tinf)
#  • oral|po    → single oral dose at time (instant event; absorption set by route)
#  • sc         → single subcutaneous dose at time (instant event; absorption set by route)
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
# Notes (decoupled semantics):
#  • Program defines only EVENTS; ROUTE defines absorption (F, ka, etc.).
#  • Never invent Tinf from route. Infusions MUST specify Tinf explicitly (or via default_Tinf).
#  • For “infusion” (and repeat: infusion), `dose` is the total amount delivered over Tinf.
#  • “onoff” expands to infusion windows: period = dose_on + dose_off, window Tinf = dose_on.
#  • Minimal validation enforces positivity for key fields (dose, Tinf, tau, count, etc.).
# ─────────────────────────────────────────────────────────────────────────────────────────────────

from typing import List, Dict, Optional

def _pos(name, v):
    if v is None or v <= 0:
        raise ValueError(f"'{name}' must be > 0")

def expand_program(
    program: List[Dict],
    default_Tinf: Optional[float] = None
) -> List[Dict]:
    """
    Convert a high-level dosing program into the 'dosing' list the simulators use:
      [{time: float, dose: float, Tinf?: float}, ...]

    Supported steps (examples):
      {"type":"bolus","time":0,"dose":100}
      {"type":"bolus","time":0,"dose":100,"tau":8,"count":6}
      {"type":"infusion","start":0,"dose":200,"Tinf":1.0}
      {"type":"repeat","pattern":"bolus","start":0,"tau":8,"count":6,"dose":100}
      {"type":"repeat","pattern":"infusion","start":0,"tau":24,"count":5,"dose":2400,"Tinf":8}
      {"type":"repeat_bolus","start":0,"tau":8,"count":6,"dose":100}
      {"type":"repeat_infusion","start":0,"tau":24,"count":5,"dose":2400,"Tinf":8}
      {"type":"titrate","start":0,"tau":24,"steps":[{"dose":200},{"dose":150},{"dose":100}]}
      {"type":"onoff","start":0,"duration":72,"dose":2400,"dose_on":8,"dose_off":16}  # infusion on/off windows
    Notes:
      • For 'infusion' and 'repeat: infusion', 'dose' is the total amount delivered over Tinf.
      • 'onoff' expands to a sequence of infusion windows: repeated (dose_on+dose_off) with per-window Tinf=dose_on.
    """
    dosing: List[Dict] = []

    for step in (program or []):
        t = step.get("type","").lower()

        # accept 'dose' as an alias for 'bolus'
        if t in ("bolus", "dose"):
            ti = float(step.get("time", step.get("start", 0.0)))
            d = float(step["dose"]); _pos("dose", d)
            if ("tau" in step) or ("count" in step):
                tau = float(step.get("tau", 0.0)); _pos("tau", tau)
                cnt = int(step.get("count", 1));  _pos("count", cnt)
                for i in range(cnt):
                    dosing.append({"time": ti + i*tau, "dose": d})
            else:
                dosing.append({"time": ti, "dose": d})

        # PO/SC single-dose events: instantaneous dose events; NO Tinf here.
        elif t in ("oral", "po", "sc", "subcut", "subcutaneous"):
            ti = float(step.get("time", step.get("start", 0.0)))
            d  = float(step["dose"]); _pos("dose", d)
            if ("tau" in step) or ("count" in step):
                tau = float(step.get("tau", 0.0)); _pos("tau", tau)
                cnt = int(step.get("count", 1));  _pos("count", cnt)
                for i in range(cnt):
                    dosing.append({"time": ti + i*tau, "dose": d})
            else:
                dosing.append({"time": ti, "dose": d})

        elif t == "infusion":
            st = float(step["start"]); d = float(step["dose"]); Tinf = float(step.get("Tinf", default_Tinf or 0.0))
            _pos("dose", d); _pos("Tinf", Tinf)
            dosing.append({"time": st, "dose": d, "Tinf": Tinf})

        elif t in ("repeat", "repeat_bolus", "repeat-infusion", "repeat_infusion", "repeat-bolus"):
            pat = step.get("pattern","bolus").lower()
            start = float(step.get("start", 0.0))
            tau   = float(step["tau"]); _pos("tau", tau)
            cnt   = int(step["count"]); _pos("count", cnt)
            d     = float(step["dose"]); _pos("dose", d)

            if pat in ("bolus",):
                for i in range(cnt):
                    dosing.append({"time": start + i*tau, "dose": d})

            elif pat == "infusion":
                Tinf = float(step.get("Tinf", default_Tinf or 0.0)); _pos("Tinf", Tinf)
                for i in range(cnt):
                    dosing.append({"time": start + i*tau, "dose": d, "Tinf": Tinf})

            # PO/SC repeat patterns behave like bolus events (no Tinf)
            elif pat in ("oral", "po", "sc", "subcut", "subcutaneous"):
                for i in range(cnt):
                    dosing.append({"time": start + i*tau, "dose": d})

            else:
                raise ValueError("repeat.pattern must be one of 'bolus' | 'infusion' | 'oral' | 'sc'")

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
