from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    Image, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
import uuid
from typing import List, Any, Dict
import pandas as pd
import json
from io import BytesIO
import numpy as np
import httpx
import io

from one_compartment_model import (
    preprocess_data,
    fit_one_compartment,
    compute_pk_parameters,
    compute_gof,
    plot_fit
)

from two_compartment_model import (
    fit_two_compartment,
    compute_pk_parameters_two,
    compute_gof_two,
    plot_fit_two
)

from three_compartment_model import (
    fit_three_compartment, 
    compute_pk_parameters_three, 
    compute_gof_three, 
    plot_fit_three
)

# from database import init_db
from reporting import generate_pdf_report
from pk_routes_one_comp import simulate_one_comp_route
from pk_routes_two_comp import simulate_two_comp_route
from pk_routes_three_comp import simulate_three_comp_route
from dosing_program import expand_program
from uq import bootstrap_uq, mcmc_uq
from sensitivity import local_sensitivity, global_prcc_sensitivity, global_sobol_sensitivity
from diagnostics import plot_residuals, plot_vpc
import base64

app = FastAPI()

# @app.on_event("startup")
# def _startup():
#     init_db()

def _pred_2c_macro(t, p):
    import numpy as np
    return p["A"] * np.exp(-p["alpha"] * t) + p["B"] * np.exp(-p["beta"] * t)

def _pred_3c_macro(t, p):
    import numpy as np
    return (p["A"] * np.exp(-p["alpha"] * t)
          + p["B"] * np.exp(-p["beta"]  * t)
          + p["C"] * np.exp(-p["gamma"] * t))

def _aicc_from_resid(resid, n, k):
    import numpy as np
    sse = float(np.sum(resid**2))
    if sse <= 0 or n <= k + 1:
        return float("inf")
    aic = n * np.log(sse / n) + 2 * k
    return aic + (2 * k * (k + 1)) / (n - k - 1)

def _json_safe(obj):
    """Recursively replace NaN/±Inf with None; convert numpy scalars/arrays to JSONable types."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    # floats (numpy or python)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if np.isfinite(obj) else None
    # ints (numpy or python)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    return obj

# allow cross-origin in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "OK"}


@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    # 1) read into DataFrame
    try:
        contents = await file.read()
        buffer = BytesIO(contents)

        if file.filename.lower().endswith((".xls", ".xlsx")):
            df = pd.read_excel(buffer)
        else:
            buffer.seek(0)
            df = pd.read_csv(buffer)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    # normalize column names
    df.rename(columns={c: c.lower() for c in df.columns}, inplace=True)

    # check for required columns
    required = {"time", "concentration"}
    missing = required - set(df.columns)
    warnings = [f"Missing required column: {m}" for m in missing] if missing else []

    # build preview (first 5 rows)
    preview = df.head().to_dict(orient="records")
    full = df.to_dict(orient="records")

    return _json_safe({
      "preview": preview,
     "data": full,
      "warnings": warnings,
      "hasDose": "dose" in df.columns
    })

@app.get("/studies")
async def list_studies():
    # load manifest
    with open("studies_manifest.json") as f:
        manifest = json.load(f)

    return manifest

@app.get("/studies/{study_id}")
async def get_study_data(study_id: str):
    # find entry
    with open("studies_manifest.json") as f:
        manifest = json.load(f)

    entry = next((s for s in manifest if s["id"] == study_id), None)

    if not entry:
        raise HTTPException(status_code=404, detail="Study not found")

    # fetch CSV from entry["url"]
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(entry["url"])
            resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch CSV: {e}")

    df = pd.read_csv(io.StringIO(resp.text))

    # rename columns to a consistent lowercase keys
    colmap = {}
    for src, dst in [
        (entry.get("timeColumn"), "time"),
        (entry.get("concColumn"), "concentration"),
        (entry.get("dosingColumn"), "dose"),
        (entry.get("subjectColumn"), "Subject"),
    ]:
        if src and src in df.columns:
            colmap[src] = dst
    df = df.rename(columns=colmap)

    return df.to_dict(orient="records")


@app.post("/fit/one_compartment")
async def fit_one(payload: dict):
    # build a DataFrame from the incoming JSON
    df = pd.DataFrame(payload.get("data", []))
    df.columns = [c.strip() for c in df.columns]  # tidy (preserve case)
    seeds = payload.get("seeds")  # optional seed guesses

    # detect subject column once, accept either 'Subject' or 'subject'
    subj_col = "Subject" if "Subject" in df.columns else ("subject" if "subject" in df.columns else None)

    results: List[Any] = []

    # group by subject if present, otherwise single "All" group
    groups = df.groupby(subj_col) if subj_col else [("All", df)]

    for subj, grp in groups:
        g = preprocess_data(grp.copy())

        warns = []
        if "concentration" in grp.columns:
            nonpos = int((grp["concentration"] <= 0).sum())
            nans   = int(grp["concentration"].isna().sum())
            if (nonpos + nans) > 0:
                warns.append(f"Non-positive concentrations filtered: {nonpos + nans}")
        if "time" in grp.columns:
            dup_t = int(grp.duplicated(subset=["time"]).sum())
            if dup_t > 0:
                warns.append(f"Duplicate time rows: {dup_t}")

        t = g["time"].values
        C = g["concentration"].values
            
        if "dose" in grp.columns:
            dose_i = float(grp["dose"].iloc[0])
        else:
            dose_i = float(payload.get("dose", 1.0))

        try:
            if seeds is not None:
                try:
                    fit = fit_one_compartment(t, C, dose_i, seeds=seeds)
                except TypeError:
                    fit = fit_one_compartment(t, C, dose_i)
            else:
                fit = fit_one_compartment(t, C, dose_i)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if isinstance(fit.get("pcov"), np.ndarray):
            fit["pcov"] = fit["pcov"].tolist()

        pk     = compute_pk_parameters(fit, dose_i)
        gof    = compute_gof(t, C, fit, dose_i)
        n   = len(t); k1 = 2
        AICc1 = gof["AIC"] + (2*k1*(k1+1)) / (n - k1 - 1) if n > (k1 + 1) else float("inf")
        gof["AICc"] = float(AICc1)

        results.append({
            "subject":   subj,
            "fit":       fit,
            "pk_params": pk,
            "gof":       gof,
            "n":         int(len(t)),
            "preprocess_warnings": warns
        })

    return _json_safe({"results": results})

@app.post("/fit/two_compartment")
async def fit_two(payload: dict):
    df_raw = pd.DataFrame(payload.get("data", []))
    df = preprocess_data(df_raw.copy())  # normalize and clean   
    seeds = payload.get("seeds")      
    sel = (payload.get("selection") or {})
    allow_demote = bool(sel.get("allow_demote", True))
    subj_col = "Subject" if "Subject" in df_raw.columns else ("subject" if "subject" in df_raw.columns else None)
    
    results = []
   
    if subj_col:
        groups = df_raw.groupby(subj_col)
    else:
        groups = [("All", df_raw)]

    for subj, grp_raw in groups:
        warns = []

        if "concentration" in grp_raw.columns:
            nonpos = int((grp_raw["concentration"] <= 0).sum())
            nans   = int(grp_raw["concentration"].isna().sum())
            if (nonpos + nans) > 0:
                warns.append(f"Non-positive concentrations filtered: {nonpos + nans}")

        if "time" in grp_raw.columns:
            dup_t = int(grp_raw.duplicated(subset=["time"]).sum())
            if dup_t > 0:
                warns.append(f"Duplicate time rows: {dup_t}")

        # fit on CLEANED copy of this subject
        grp   = preprocess_data(grp_raw.copy())
        t      = grp["time"].values
        C      = grp["concentration"].values
        dose_i = float(grp_raw["dose"].iloc[0]) if "dose" in grp_raw.columns else float(payload.get("dose", 1.0))

        # fit 2c (with optional seeds) 
        try:
            if seeds is not None:
                try:
                    fit2 = fit_two_compartment(t, C, dose_i, seeds=seeds)
                except TypeError:
                    fit2 = fit_two_compartment(t, C, dose_i)
            else:
                fit2 = fit_two_compartment(t, C, dose_i)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        gof2 = compute_gof_two(t, C, fit2)
        n    = len(t)
        k2   = 4
        AICc2 = gof2["AIC"] + (2*k2*(k2+1))/max(n - k2 - 1, 1) if n > (k2 + 1) else float("inf")

        # fit 1c for guardrail 
        fit1 = fit_one_compartment(t, C, dose_i)
        gof1 = compute_gof(t, C, fit1, dose_i)
        k1   = 2
        AICc1 = gof1["AIC"] + (2*k1*(k1+1))/max(n - k1 - 1, 1) if n > (k1 + 1) else float("inf")

        # simple identifiability heuristics for 2c 
        A     = float(fit2.get("A", np.nan))
        B     = float(fit2.get("B", np.nan))
        alpha = float(fit2.get("alpha", np.nan))
        beta  = float(fit2.get("beta", np.nan))
        B_rel    = (abs(B) / max(abs(A) + abs(B), 1e-12)) if np.isfinite(A) and np.isfinite(B) else 0.0
        sep_rel2 = (abs(alpha - beta) / max(alpha, beta)) if np.isfinite(alpha) and np.isfinite(beta) and max(alpha, beta) > 0 else 0.0

        # Demote if: thin data OR (1c ~ 2c by AICc) AND 2c looks degenerate
        propose_demote = (n < 6) or (((B_rel < 0.03) or (sep_rel2 < 0.05)) and not (AICc2 + 2 < AICc1))
        # Honor user preference
        use_one = allow_demote and propose_demote

        selection_diag = {
            "AICc1": float(AICc1),
            "AICc2": float(AICc2),
            "delta21": float(AICc2 - AICc1),  # negative favors 2c
            "sep_rel2": float(sep_rel2),
            "B_rel": float(B_rel),
            "n": int(n),
            "demoted": bool(use_one),
            "allow_demote": bool(allow_demote),
            "would_demote": bool(propose_demote)
        }

        if use_one:
            gof1 = {**gof1, "AICc": float(AICc1)}
            pk_params = compute_pk_parameters(fit1, dose_i)
            results.append({
                "subject":   subj,
                "fit":       fit1,
                "pk_params": pk_params,
                "gof":       gof1,
                "n":         int(n),
                "selection_diag": {**selection_diag, "reason": "ΔAICc<2 vs 1c and/or poor rate separation or tiny B, or n<6."},
                "preprocess_warnings": warns,
                "note": "Auto-demoted to 1-comp."
            })

        else:
            gof2 = {**gof2, "AICc": float(AICc2)}
            pk_params = compute_pk_parameters_two(fit2, dose_i)
            results.append({
                "subject":   subj,
                "fit":       fit2,
                "pk_params": pk_params,
                "gof":       gof2,
                "n":         int(n),
                "selection_diag": selection_diag,
                "preprocess_warnings": warns,
                **({ "note": "Auto-demotion disabled by user; kept 2-comp." }
                   if (not allow_demote and propose_demote) else {})
            })

    return _json_safe({"results": results})

@app.post("/fit/three_compartment")
async def fit_three(payload: dict):
    df = pd.DataFrame(payload.get("data", []))
    df.columns = [c.strip() for c in df.columns]
    seeds = payload.get("seeds")

    sel = (payload.get("selection") or {})
    crit = str(sel.get("criterion", "AICc_linear")).lower()   # "aicc_linear" | "aicc_log"
    delta_keep = float(sel.get("deltaAICc", 2.0))
    sep_min = float(sel.get("sep_rel_min", 0.05))
    tail_min = float(sel.get("tail_auc_min", 0.08))
    force_three = bool(sel.get("force_three", False))
    if "allow_demote" in sel:
        force_three = not bool(sel["allow_demote"])

    subj_col = "Subject" if "Subject" in df.columns else ("subject" if "subject" in df.columns else None)
    results = []
    groups = df.groupby(subj_col) if subj_col else [("All", df)]

    for subj, grp in groups:
        warns = []

        if "concentration" in grp.columns:
            nonpos = int((grp["concentration"] <= 0).sum())
            nans   = int(grp["concentration"].isna().sum())
            if (nonpos + nans) > 0:
                warns.append(f"Non-positive concentrations filtered: {nonpos + nans}")

        if "time" in grp.columns:
            dup_t = int(grp.duplicated(subset=["time"]).sum())
            if dup_t > 0:
                warns.append(f"Duplicate time rows: {dup_t}")

        t = grp["time"].values
        C = grp["concentration"].values
        dose_i = float(grp["dose"].iloc[0]) if "dose" in grp.columns else float(payload.get("dose", 1.0))
        n = len(t)

        # try 3c
        try:
            # Pass seeds only if provided; fall back if the function doesn't accept it
            if seeds is not None:
                try:
                    fit3 = fit_three_compartment(t, C, dose_i, seeds=seeds)
                except TypeError:
                    # fit_three_compartment doesn't support `seeds`
                    fit3 = fit_three_compartment(t, C, dose_i)
            else:
                fit3 = fit_three_compartment(t, C, dose_i)

            gof3 = compute_gof_three(t, C, fit3)

        except RuntimeError as e:
            # if 3c fails outright, surface error (UI/report already has fallback paths)
            raise HTTPException(status_code=400, detail=str(e))


        # fit 2c for model selection guardrail
        try:
            fit2 = fit_two_compartment(t, C, dose_i)
            gof2 = compute_gof_two(t, C, fit2)
            # AICc(2c) linear-scale default (may be overridden below)
            k2 = 4
            AICc2 = gof2["AIC"] + (2*k2*(k2+1))/max(n - k2 - 1, 1) if n > (k2 + 1) else float('inf')
        except Exception:
            fit2, gof2, AICc2 = None, None, float('inf')

        # Recompute AICc for BOTH models under the chosen criterion
        eps   = 1e-12
        AICc3 = float("inf")
        AICc2 = float("inf") if fit2 is None else AICc2
        if crit == "aicc_log":
            try:
                Cp3 = _pred_3c_macro(t, fit3)
                r3  = np.log(np.maximum(C, eps)) - np.log(np.maximum(Cp3, eps))
                AICc3 = _aicc_from_resid(r3, n, 6)
            except Exception:
                AICc3 = float("inf")
            if fit2 is not None:
                try:
                    Cp2 = _pred_2c_macro(t, fit2)
                    r2  = np.log(np.maximum(C, eps)) - np.log(np.maximum(Cp2, eps))
                    AICc2 = _aicc_from_resid(r2, n, 4)
                except Exception:
                    AICc2 = float("inf")
        else:  # aicc_linear
            try:
                Cp3 = _pred_3c_macro(t, fit3)
                r3  = C - Cp3
                AICc3 = _aicc_from_resid(r3, n, 6)
            except Exception:
                AICc3 = float("inf")
            if fit2 is not None:
                try:
                    Cp2 = _pred_2c_macro(t, fit2)
                    r2  = C - Cp2
                    AICc2 = _aicc_from_resid(r2, n, 4)
                except Exception:
                    AICc2 = float("inf")

        # Also fit 1c for possible cascade demotion
        fit1 = fit_one_compartment(t, C, dose_i)
        gof1 = compute_gof(t, C, fit1, dose_i)
        k1   = 2
        AICc1 = gof1["AIC"] + (2*k1*(k1+1))/max(n - k1 - 1, 1) if n > (k1 + 1) else float("inf")

        # separation + tail strength guard (scale-invariant & amplitude-aware)
        sep_log   = float(gof3.get("rate_sep_log", np.nan))
        tail_frac = float(gof3.get("tail_auc_frac", np.nan))
        sep_rel   = float(gof3.get("rate_sep_rel", 0.0))
        bad_sep   = (not np.isfinite(sep_log)) or (sep_log < np.log(1.5))
        weak_tail = (not np.isfinite(tail_frac)) or (tail_frac < tail_min)

        selection_diag = {
            "AICc2": float(AICc2),
            "AICc3": float(AICc3),
            "delta": float(AICc3 - AICc2),   # 3c − 2c (negative favors 3c)
            "sep_rel": float(sep_rel),
            "n": int(n),
            "criterion": crit,
            "delta_keep": float(delta_keep),
            "sep_rel_min": float(sep_min),
            "tail_auc_min": float(tail_min),
            "allow_demote": (not force_three)
        }

        reason_str = f"ΔAICc<{delta_keep:g} and/or poor 3c rate separation or n<8."

        # Demote if too few points OR (poor separation/tail) AND 3c not clearly better
        demote = (n < 8) or (((sep_rel < sep_min) or bad_sep or weak_tail) and not (AICc3 + delta_keep < AICc2))
        
        if force_three:
            demote = False

        if demote:
            # Decide whether 2c is still over-parameterized vs 1c
            if fit2 is not None:
                A     = float(fit2.get("A", np.nan))
                B     = float(fit2.get("B", np.nan))
                alpha = float(fit2.get("alpha", np.nan))
                beta  = float(fit2.get("beta", np.nan))
                B_rel    = (abs(B) / max(abs(A) + abs(B), 1e-12)) if np.isfinite(A) and np.isfinite(B) else 0.0
                sep_rel2 = (abs(alpha - beta) / max(alpha, beta)) if np.isfinite(alpha) and np.isfinite(beta) and max(alpha, beta) > 0 else 0.0
                use_one  = (n < 6) or (((B_rel < 0.03) or (sep_rel2 < 0.05)) and not (AICc2 + 2 < AICc1))
            else:
                B_rel, sep_rel2, use_one = np.nan, np.nan, True

            if use_one:
                pk_params = compute_pk_parameters(fit1, dose_i)
                results.append({
                    "subject": subj,
                    "fit": fit1,
                    "pk_params": pk_params,
                    "gof": gof1,
                    "n": int(n),
                    "selection_diag": {**selection_diag,
                        "AICc1": float(AICc1),
                        "sep_rel2": (float(sep_rel2) if np.isfinite(sep_rel2) else None),
                        "B_rel": (float(B_rel) if np.isfinite(B_rel) else None),
                        "demoted": True,
                        "reason": "3→2 demotion + 2→1 (ΔAICc<2 vs 1c and/or poor 2c separation/tiny B, or n<6)."
                    },
                    "preprocess_warnings": warns,
                    "note": "Auto-demoted to 1-comp."
                })

            else:
                pk_params = compute_pk_parameters_two(fit2, dose_i)
                results.append({
                    "subject": subj,
                    "fit": fit2,
                    "pk_params": pk_params,
                    "gof": {**gof2, "AICc": float(AICc2)},
                    "n": int(n),
                    "selection_diag": {**selection_diag,
                        "AICc1": float(AICc1),
                        "sep_rel2": float(sep_rel2),
                        "B_rel": float(B_rel),
                        "demoted": True,
                        "reason": reason_str
                    },
                    "note": "Auto-demoted to 2-comp."
                })

        else:
            pk_params = compute_pk_parameters_three(fit3, dose_i)
            results.append({
                "subject": subj,
                "fit": fit3,
                "pk_params": pk_params,
                "gof": gof3,
                "n": int(n),
                "selection_diag": {**selection_diag, "AICc1": float(AICc1), "demoted": False},
                "preprocess_warnings": warns
            })
    return _json_safe({"results": results})

@app.post("/report")
async def create_report(payload: dict = Body(...)):
    """
    Expects JSON:
    {
      "data": [{time:…, concentration:…}, …],
      "metadata": {study_id, species, route, dose}
    }
    Returns: PDF file response.
    """
    # 1) Build & preprocess DataFrame
    df = pd.DataFrame(payload["data"])
    df = preprocess_data(df)

    # 2) Extract arrays & parameters
    t = df["time"].values
    C = df["concentration"].values
    model = payload["metadata"].get("model", "one")

    # 3) Build a multi-page PDF: one page per Subject (or "All" if no Subject)
    out_buf  = BytesIO()
    doc      = SimpleDocTemplate(out_buf, pagesize=letter)
    styles   = getSampleStyleSheet()
    h2_break = ParagraphStyle(
        "H2Break", parent=styles["Heading2"], keepWithNext=False, spaceAfter=0
    )
    elems    = []

    subj_col = "subject" if "subject" in df.columns else ("Subject" if "Subject" in df.columns else None)
    groups = list(df.groupby(subj_col)) if subj_col else [("All", df)]

    for idx, (subj, grp) in enumerate(groups):
        mdl_for_page = model
        selection_diag = None

        # preprocess this subject
        df_sub = preprocess_data(grp[["time", "concentration"]].copy())
        t_sub  = df_sub["time"].values
        C_sub  = df_sub["concentration"].values

        # if the DataFrame itself has a dose column, use it; otherwise fall back to metadata.dose
        if "dose" in grp.columns:
            dose_sub = float(grp["dose"].iloc[0])
        else:
            md_safe = payload.get("metadata", {})
            if "dose" not in md_safe:
                raise HTTPException(status_code=400, detail="Missing 'dose' in metadata or data column.")
            dose_sub = float(md_safe["dose"])

        # fit + PK + GOF + plot (branch by model)
        if model == "two":
            # --- Fit both 2c and 1c to support demotion identical to /fit/two_compartment ---
            fit2       = fit_two_compartment(t_sub, C_sub, dose_sub)
            gof2       = compute_gof_two(t_sub, C_sub, fit2)
            n_pts_page = len(t_sub)
            k2         = 4
            AICc2      = gof2["AIC"] + (2*k2*(k2+1))/max(n_pts_page - k2 - 1, 1) if n_pts_page > (k2 + 1) else float("inf")

            fit1  = fit_one_compartment(t_sub, C_sub, dose_sub)
            gof1  = compute_gof(t_sub, C_sub, fit1, dose_sub)
            k1    = 2
            AICc1 = gof1["AIC"] + (2*k1*(k1+1))/max(n_pts_page - k1 - 1, 1) if n_pts_page > (k1 + 1) else float("inf")

            # Identifiability heuristics (match /fit/two_compartment)
            A     = float(fit2.get("A", np.nan))
            B     = float(fit2.get("B", np.nan))
            alpha = float(fit2.get("alpha", np.nan))
            beta  = float(fit2.get("beta", np.nan))
            B_rel    = (abs(B) / max(abs(A) + abs(B), 1e-12)) if np.isfinite(A) and np.isfinite(B) else 0.0
            sep_rel2 = (abs(alpha - beta) / max(alpha, beta)) if np.isfinite(alpha) and np.isfinite(beta) and max(alpha,beta) > 0 else 0.0
            allow_demote = bool((payload.get("metadata") or {}).get("allow_demote", True))

            # Propose demotion if thin data OR (degenerate 2c) AND 2c is not better by ≥2 AICc
            propose_demote = (n_pts_page < 6) or (((B_rel < 0.03) or (sep_rel2 < 0.05)) and not (AICc2 + 2 < AICc1))
            use_one = allow_demote and propose_demote

            # Record diagnostics for PDF badges/section
            selection_diag = {
                "AICc1": float(AICc1),
                "AICc2": float(AICc2),
                "delta21": float(AICc2 - AICc1),   # positive ⇒ 1c preferred
                "sep_rel2": float(sep_rel2),
                "B_rel": float(B_rel),
                "n": int(n_pts_page),
                "allow_demote": bool(allow_demote),
                "would_demote": bool(propose_demote),
                "demoted": bool(use_one),
            }

            if use_one:
                mdl_for_page = "one"
                elems.append(Paragraph(
                    "Note: Auto-demoted to one-compartment "
                    "(ΔAICc<2 vs 1c and/or poor rate separation or tiny B, or n<6).",
                    styles["Italic"]))
                elems.append(Spacer(1, 6))

                fit       = fit1
                pk_params = compute_pk_parameters(fit1, dose_sub)
                gof       = {**gof1, "AICc": float(AICc1)}

                meta_events   = payload["metadata"].get("dosing", None)
                dosing_events = meta_events if meta_events else [{"time": 0.0, "dose": dose_sub, **(
                    {"Tinf": float(payload["metadata"].get("Tinf", 0.0))} if payload["metadata"].get("Tinf") else {}
                )}]
                # 1c plotting (no mechanistic schematic)
                buf_lin, buf_log, buf_dose = plot_fit(t_sub, C_sub, fit, dose_sub, dosing=dosing_events)
                buf_mech = None
            else:
                mdl_for_page = "two"
                fit       = fit2
                pk_params = compute_pk_parameters_two(fit2, dose_sub)
                gof       = {**gof2, "AICc": float(AICc2)}

                # only draw mechanistic if all params are present
                md = payload["metadata"]
                k10 = float(md.get("k10", 0.1))
                k12 = float(md.get("k12", 0.2))
                k21 = float(md.get("k21", 0.05))
                V1  = float(md.get("V1",  5.0))
                V2  = float(md.get("V2", 20.0))

                meta_events   = payload["metadata"].get("dosing", None)
                dosing_events = meta_events if meta_events else [{"time": 0.0, "dose": dose_sub, **(
                    {"Tinf": float(payload["metadata"].get("Tinf", 0.0))} if payload["metadata"].get("Tinf") else {}
                )}]
                buf_lin, buf_log, buf_mech, buf_dose = plot_fit_two(
                    t_sub, C_sub, fit, k10, k12, k21, V1, V2, dosing=dosing_events)

        elif model == "three":
            try:
                if len(t_sub) < 7:
                    raise RuntimeError("Too few points for a stable three-compartment fit; using 2c.")

                # selection settings
                md = payload["metadata"]
                crit = str(md.get("criterion", "AICc_linear")).lower()   # "aicc_linear" | "aicc_log"
                delta_keep = float(md.get("deltaAICc", 2.0))
                sep_min    = float(md.get("sep_rel_min", 0.05))
                tail_min   = float(md.get("tail_auc_min", 0.08))
                allow_demote = bool(md.get("allow_demote", True))
                force_three = bool(md.get("force_three", False)) or (not allow_demote)

                # --- fit 3-comp and compute GOF ---
                fit3 = fit_three_compartment(t_sub, C_sub, dose_sub)
                gof3 = compute_gof_three(t_sub, C_sub, fit3)

                # --- also fit 2-comp for model selection guardrail ---
                try:
                    fit2 = fit_two_compartment(t_sub, C_sub, dose_sub)
                    gof2 = compute_gof_two(t_sub, C_sub, fit2)
                except Exception:
                    fit2, gof2 = None, None  # fall back to 3c-only comparison below

                # AICc and rate-separation checks (driven by criterion) 
                n = len(t_sub); k2, k3 = 4, 6
                eps = 1e-12

                # 3c AICc
                Cp3 = _pred_3c_macro(t_sub, fit3)
                if crit == "aicc_log":
                    r3 = np.log(np.maximum(C_sub, eps)) - np.log(np.maximum(Cp3, eps))
                else:
                    r3 = C_sub - Cp3
                AICc3 = _aicc_from_resid(r3, n, k3)

                # 2c AICc (only if the 2c fit succeeded)
                if fit2 is not None:
                    Cp2 = _pred_2c_macro(t_sub, fit2)
                    if crit == "aicc_log":
                        r2 = np.log(np.maximum(C_sub, eps)) - np.log(np.maximum(Cp2, eps))
                    else:
                        r2 = C_sub - Cp2
                    AICc2 = _aicc_from_resid(r2, n, k2)
                else:
                    AICc2 = float("inf")
                    
                sep_log   = float(gof3.get("rate_sep_log", np.nan))
                tail_frac = float(gof3.get("tail_auc_frac", np.nan))
                bad_sep   = (not np.isfinite(sep_log)) or (sep_log < np.log(1.5))
                weak_tail = (not np.isfinite(tail_frac)) or (tail_frac < tail_min)
                sep_rel = float(gof3.get("rate_sep_rel", 0.0))

                # demotion rule: MATCH /fit/three_compartment
                use_two = (n < 8) or (((sep_rel < sep_min) or bad_sep or weak_tail)
                                       and not (AICc3 + delta_keep < AICc2))

                # Honor user preference
                if force_three and use_two:
                    elems.append(Paragraph(
                        f"Note: Auto-demotion disabled by user; keeping three-compartment.",
                        styles["Italic"]))
                    use_two = False

                # record model-selection diagnostics for the PDF page
                selection_diag = {
                    "AICc2": float(AICc2),
                    "AICc3": float(AICc3),
                    "delta": float(AICc3 - AICc2),  # 3c − 2c (negative favors 3c)
                    "sep_rel": float(sep_rel),
                    "n": int(n),
                    "criterion": crit,
                    "delta_keep": float(delta_keep),
                    "sep_rel_min": float(sep_min),
                    "tail_auc_min": float(tail_min),
                    "demoted": bool(use_two),
                }

                if use_two:
                    mdl_for_page = "two"
                    elems.append(Paragraph(
                        f"Note: Auto-demoted to two-compartment for Subject {subj} "
                        f"(ΔAICc<{delta_keep:g} and/or poor 3c rate separation / weak tail or n<8).",
                        styles["Italic"]))
                    elems.append(Spacer(1, 6))

                    fit = fit2
                    pk_params = compute_pk_parameters_two(fit2, dose_sub)
                    gof = {**gof2, "AICc": float(AICc2)}

                    k10 = float(md.get("k10", 0.1))
                    k12 = float(md.get("k12", 0.2))
                    k21 = float(md.get("k21", 0.05))
                    V1  = float(md.get("V1", 5.0))
                    V2  = float(md.get("V2", 20.0))
                    meta_events = payload["metadata"].get("dosing", None)
                    dosing_events = meta_events if meta_events else [{
                        "time": 0.0, "dose": dose_sub,
                        **({"Tinf": float(payload["metadata"].get("Tinf", 0.0))}
                           if payload["metadata"].get("Tinf") else {})
                    }]
                    buf_lin, buf_log, buf_mech, buf_dose = plot_fit_two(
                        t_sub, C_sub, fit, k10, k12, k21, V1, V2, dosing=dosing_events)

                else:
                    mdl_for_page = "three"
                    fit = fit3
                    pk_params = compute_pk_parameters_three(fit3, dose_sub)
                    gof = gof3

                    k10 = float(md.get("k10", 0.1))
                    k12 = float(md.get("k12", 0.2))
                    k21 = float(md.get("k21", 0.05))
                    k13 = float(md.get("k13", 0.1))
                    k31 = float(md.get("k31", 0.03))
                    V1  = float(md.get("V1", 5.0))
                    V2  = float(md.get("V2", 20.0))
                    V3  = float(md.get("V3", 30.0))
                    meta_events = payload["metadata"].get("dosing", None)
                    dosing_events = meta_events if meta_events else [{
                        "time": 0.0, "dose": dose_sub,
                        **({"Tinf": float(payload["metadata"].get("Tinf", 0.0))}
                           if payload["metadata"].get("Tinf") else {})
                    }]
                    buf_lin, buf_log, buf_mech, buf_dose = plot_fit_three(
                        t_sub, C_sub, fit, k10, k12, k21, k13, k31, V1, V2, V3, dosing=dosing_events)

            except RuntimeError as e:
                # Fallback on hard failure
                mdl_for_page = "two"
                elems.append(Paragraph(
                    f"Note: three-compartment fit failed for Subject {subj} "
                    f"({str(e)}). Falling back to two-compartment fit.", styles["Italic"]))
                elems.append(Spacer(1, 6))
                fit = fit_two_compartment(t_sub, C_sub, dose_sub)
                pk_params = compute_pk_parameters_two(fit, dose_sub)
                gof = compute_gof_two(t_sub, C_sub, fit)
                md = payload["metadata"]
                k10 = float(md.get("k10", 0.1))
                k12 = float(md.get("k12", 0.2))
                k21 = float(md.get("k21", 0.05))
                V1  = float(md.get("V1", 5.0))
                V2  = float(md.get("V2", 20.0))
                meta_events = payload["metadata"].get("dosing", None)
                dosing_events = meta_events if meta_events else [{
                    "time": 0.0, "dose": dose_sub,
                    **({"Tinf": float(payload["metadata"].get("Tinf", 0.0))}
                       if payload["metadata"].get("Tinf") else {})
                }]
                buf_lin, buf_log, buf_mech, buf_dose = plot_fit_two(
                    t_sub, C_sub, fit, k10, k12, k21, V1, V2, dosing=dosing_events)

        else:
            fit       = fit_one_compartment(t_sub, C_sub, dose_sub)
            pk_params = compute_pk_parameters(fit, dose_sub)
            gof       = compute_gof(t_sub, C_sub, fit, dose_sub)
            meta_events = payload["metadata"].get("dosing", None)
            dosing_events = meta_events if meta_events else [{"time": 0.0, "dose": dose_sub, **(
                {"Tinf": float(payload["metadata"].get("Tinf", 0.0))} if payload["metadata"].get("Tinf") else {}
            )}]
            buf_lin, buf_log, buf_dose = plot_fit(t_sub, C_sub, fit, dose_sub, dosing=dosing_events)

        # Subject header
        elems.append(Paragraph(f"Subject {subj}", styles["Title"]))
        elems.append(Spacer(1, 12))

        # Mechanistic central vs. peripheral (use effective page model after demotion)
        if mdl_for_page in ("two","three") and (buf_mech is not None):
            elems.append(Paragraph("Central vs. Peripheral Compartments", styles["Heading2"]))
            elems.append(Image(buf_mech, width=400, height=200))
            elems.append(Spacer(1, 12))

        # Metadata table
        meta = {k: (v if isinstance(v,(str,int,float)) else json.dumps(v))
        for k,v in payload["metadata"].items()}
        meta["subject"] = subj
        meta_data = [["Field", "Value"]] + [[k, str(v)] for k, v in meta.items()]
        tbl = Table(meta_data, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.grey),
        ]))
        elems.append(Paragraph("Study Metadata", styles["Heading2"]))
        elems.append(tbl)
        elems.append(Spacer(1, 12))

        # Data summary (+ KPIs with units)
        # Units (optional in metadata; defaults sensible for PK)
        time_units = (payload.get("metadata", {}) or {}).get("time_units", "h")
        conc_units = (payload.get("metadata", {}) or {}).get("conc_units", "a.u.")

        # Observed n, t_min, t_max
        n_pts = int(len(df_sub))
        t_min = float(df_sub.time.min()) if n_pts > 0 else float("nan")
        t_max = float(df_sub.time.max()) if n_pts > 0 else float("nan")

        # Observed Cmax (based on cleaned data)
        if n_pts > 0:
            idx_cmax = int(np.argmax(C_sub))
            Cmax_obs = float(C_sub[idx_cmax])
        else:
            Cmax_obs = float("nan")

        # log-slope on a subset (for half-life and early/late slopes)
        def _log_slope(t_arr, c_arr):
            t_arr = np.asarray(t_arr, dtype=float)
            c_arr = np.asarray(c_arr, dtype=float)
            m = (np.isfinite(t_arr)) & (np.isfinite(c_arr)) & (c_arr > 0)
            if m.sum() >= 2:
                # slope of ln C vs t
                slope, _ = np.polyfit(t_arr[m], np.log(c_arr[m]), 1)
                return float(slope)
            return float("nan")

        # Global log-linear half-life from all positive points
        m_global = _log_slope(t_sub, C_sub)
        if np.isfinite(m_global) and m_global < 0:
            t_half_global = float(np.log(2) / (-m_global))
        else:
            t_half_global = None

        # Early vs late log-slope ratio (dimensionless)
        if np.isfinite(t_min) and np.isfinite(t_max) and t_max > t_min:
            q_lo, q_hi = np.quantile(t_sub, [0.33, 0.67])
            me = _log_slope(t_sub[t_sub <= q_lo], C_sub[t_sub <= q_lo])
            ml = _log_slope(t_sub[t_sub >= q_hi], C_sub[t_sub >= q_hi])
            if np.isfinite(me) and np.isfinite(ml) and (ml != 0):
                ml_ratio = float(abs(me) / abs(ml))
            else:
                ml_ratio = None
        else:
            ml_ratio = None

        summary = [
            ["n", n_pts],
            ["Time span (min → max)", f"{t_min:.2f} → {t_max:.2f} {time_units}"],
            ["C_max (observed)", f"{Cmax_obs:.3g}" + (f" {conc_units}" if conc_units else "")],
            ["Global t½ (log-linear)", f"{t_half_global:.2f} {time_units}" if t_half_global is not None else "—"],
            ["|m_early|/|m_late| (log-slopes)", f"{ml_ratio:.2f}" if ml_ratio is not None else "—"],
        ]
        sum_tbl = Table(summary, hAlign="LEFT")
        sum_tbl.setStyle(TableStyle([("GRID", (0,0),(-1,-1), 0.5, colors.grey)]))
        elems.append(Paragraph("Data Summary", styles["Heading2"]))
        elems.append(sum_tbl)
        elems.append(Spacer(1, 12))

        # Fit results (parameters & 95% CI)
        rows = [["Parameter","Estimate","95% CI"]]
        mdl = mdl_for_page

        if mdl == "one":
            # one-compartment parameters
            for name in ("Vd","kel"):
                est = fit[name]; ci = fit[f"{name}_ci"]
                rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
            # derived PK parameters
            for name in ("Cl","t_half","C0","AUC","MRT"):
                est = pk_params[name]; ci = pk_params[f"{name}_ci"]
                rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])

        elif mdl == "two":
            # two-compartment macro parameters
            for name in ("A","alpha","B","beta"):
                est = fit[name]; ci = fit[f"{name}_ci"]
                rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])

            # derived mechanistic parameters
            md   = payload["metadata"]
            k10  = float(md.get("k10", 0.0))
            V1   = float(md.get("V1",  0.0))
            V2   = float(md.get("V2",  0.0))
            # steady-state volume and clearance
            Vd_ss = V1 + V2
            Cl    = k10 * V1
            rows.append(["Vd_ss", f"{Vd_ss:.3g}", ""])
            rows.append(["Cl",    f"{Cl:.3g}",    ""])

        elif mdl == "three":
            # three-compartment macro parameters
            for name in ("A","alpha","B","beta","C","gamma"):
                est = fit[name]; ci = fit[f"{name}_ci"]
                rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
            # derived mechanistic-ish quick calcs if provided
            md  = payload["metadata"]
            k10 = float(md.get("k10", 0.0))
            V1  = float(md.get("V1", 0.0))
            V2  = float(md.get("V2", 0.0))
            V3  = float(md.get("V3", 0.0))
            Vd_ss = V1 + V2 + V3 if all(v > 0 for v in (V1, V2, V3)) else 0.0
            Cl    = k10 * V1 if (k10 > 0 and V1 > 0) else 0.0
            rows.append(["Vd_ss", f"{Vd_ss:.3g}", ""])
            rows.append(["Cl",    f"{Cl:.3g}",    ""])

        else:
            pass

        fit_tbl = Table(rows, hAlign="LEFT")
        fit_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,0), colors.lightgrey),
            ("GRID",       (0,0),(-1,-1), 0.5, colors.grey),
        ]))
        elems.append(Paragraph("Fit Results (with 95% CI)", styles["Heading2"]))
        elems.append(fit_tbl)
        elems.append(Spacer(1, 12))

        # Goodness-of-fit
        gof_data = [["R²", f"{gof['R2']:.3f}"], ["AIC", f"{gof['AIC']:.1f}"]]
        if "AICc" in gof and np.isfinite(gof["AICc"]):
            gof_data.append(["AICc", f"{gof['AICc']:.1f}"])
        gof_tbl  = Table(gof_data, hAlign="LEFT")
        gof_tbl.spaceBefore = 20
        gof_tbl.setStyle(TableStyle([("GRID", (0,0),(-1,-1), 0.5, colors.grey)]))
        elems.append(Spacer(1, 20))
        elems.append(Paragraph("Goodness-of-Fit", h2_break))
        elems.append(gof_tbl)
        elems.append(Spacer(1, 12))

        if selection_diag is not None:
            # 3c vs 2c diagnostics OR 2c vs 1c diagnostics depending on keys present
            if "AICc3" in selection_diag:
                crit_label = selection_diag.get("criterion", "aicc_log")
                crit_pretty = "AICc (log)" if crit_label == "aicc_log" else "AICc (linear)"
                diag_rows = [
                    ["Criterion", crit_pretty],
                    ["AICc (2c)", f"{selection_diag['AICc2']:.2f}"],
                    ["AICc (3c)", f"{selection_diag['AICc3']:.2f}"],
                    ["ΔAICc (3c − 2c)", f"{selection_diag['delta']:.2f}"],
                    ["rate_sep_rel (3c)", f"{selection_diag['sep_rel']:.3f}"],
                ]
            else:
                # two-comp selection diagnostics (2c vs 1c)
                diag_rows = [
                    ["AICc (1c)", f"{selection_diag['AICc1']:.2f}"],
                    ["AICc (2c)", f"{selection_diag['AICc2']:.2f}"],
                    ["ΔAICc (2c − 1c)", f"{selection_diag['delta21']:.2f}"],
                    ["sep_rel (2c)", f"{selection_diag['sep_rel2']:.3f}"],
                    ["B_rel (2c)", f"{selection_diag['B_rel']:.3f}"],
                    ["Demoted", "Yes" if selection_diag.get("demoted") else "No"],
                ]

            diag_tbl = Table(diag_rows, hAlign="LEFT")
            diag_tbl.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ]))

            elems.append(Paragraph("Model Selection Diagnostics", styles["Heading2"]))
            elems.append(diag_tbl)
            elems.append(Spacer(1, 12))

        # Diagnostics (Residuals + VPC)
        try:
            # Map UI labels → diagnostics' expected keys
            model_key = {"one":"1c", "two":"2c", "three":"3c"}[mdl_for_page]
            
            res_buf = plot_residuals(
                t_sub, C_sub, fit, model_key,
                dose_sub if (model_key == "1c") else None
            )

            vpc_buf = plot_vpc(
                t_sub, fit, model_key,
                dose_sub if (model_key == "1c") else None,
                n_draws=200
            )
            
            elems.append(Paragraph("Residual Diagnostics", styles["Heading2"]))
            elems.append(Image(res_buf, width=400, height=200))
            elems.append(Spacer(1, 12))
            elems.append(Paragraph("Visual Predictive Check (5–95%)", styles["Heading2"]))
            elems.append(Image(vpc_buf, width=400, height=200))
            elems.append(Spacer(1, 12))
        except Exception as _:
            pass

        # Plots: linear & semilog 
        elems.append(Spacer(1, 30))       
        elems.append(Paragraph("Linear Fit", styles["Heading2"]))
        elems.append(Image(buf_lin, width=400, height=200))
        elems.append(Spacer(1, 12))
        elems.append(Paragraph("Semilog Fit", styles["Heading2"]))
        elems.append(Image(buf_log, width=400, height=200))
        elems.append(Spacer(1, 160))
        elems.append(Paragraph("Dosing Timeline", styles["Heading2"]))
        elems.append(Image(buf_dose, width=400, height=120))

        # page break between groups, not after the last one
        if idx < len(groups) - 1:
            elems.append(PageBreak())

    # write out the PDF
    try:
        doc.build(elems)
        out_buf.seek(0)
        headers = {"Content-Disposition": 'attachment; filename="EVPK_Report.pdf"'}
        return StreamingResponse(out_buf, media_type="application/pdf", headers=headers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

# if two 3c rates are nearly equal, merge them and return a 2c macro set
def _maybe_demote_3c_macro(params: Dict, tol: float = 0.02):
    """
    If any pair among (alpha, beta, gamma) are within 'tol' relative separation,
    merge their amplitudes and return a 2-compartment macro dict {A,alpha,B,beta}.
    Returns None if no merge.
    """
    try:
        A, B, C = float(params["A"]), float(params["B"]), float(params["C"])
        al, be, ga = float(params["alpha"]), float(params["beta"]), float(params["gamma"])
    except Exception:
        return None
    
    rates = np.array([al, be, ga], dtype=float)
    amps  = np.array([A,  B,  C],  dtype=float)

    if not (np.all(np.isfinite(rates)) and np.all(np.isfinite(amps))):
        return None
    
    pairs = [(0,1),(0,2),(1,2)]
    for i, j in pairs:
        ri, rj = rates[i], rates[j]

        if min(ri, rj) <= 0:
            continue

        rel_sep = abs(ri - rj) / max(ri, rj)

        if rel_sep < tol:
            # merge i & j into one exponential with amp sum and rate as amp-weighted avg
            merged_rate = (amps[i]*ri + amps[j]*rj) / (amps[i] + amps[j]) if (amps[i]+amps[j]) != 0 else max(ri, rj)
            merged_amp  = amps[i] + amps[j]
            k = 3 - i - j  # the remaining index

            return {
                "A": float(merged_amp), "alpha": float(merged_rate),
                "B": float(amps[k]),   "beta":  float(rates[k])
            }
        
    return None

@app.post("/simulate_pk")
async def simulate_pk(payload: dict = Body(...)):
    """
    PK simulation for multiple dosing routes.
    Body:
    {
    "model": "1c" | "2c" | "3c",
    "route": "iv_bolus" | "iv_infusion" | "oral" | "sc",
    "params": {
        // 1c:
        //   Vd, kel, (F?, ka?, Tinf?)

        // 2c (choose ONE set):
        //   A, alpha, B, beta, (F?, ka?, Tinf?)
        //   OR k10, k12, k21, V1, (F?, ka?, Tinf?)

        // 3c (choose ONE set):
        //   A, alpha, B, beta, C, gamma, (F?, ka?, Tinf?)
        //   OR k10, k12, k21, k13, k31, V1, V2, V3, (F?, ka?, Tinf?)
    },
    // dosing/program/repeat as before…
    "t_end": 24.0,
    "dt": 0.1
    // Optional: estimate params from raw data and use them here
    "estimate_from_data": true,          
    "data": [{ "time": ..., "concentration": ..., "dose"?: ... , "Subject"?: ... }, ...],
    "dose": 100,          // used for fitting if data lacks a 'dose' column
    "fit_subject": "S01"  // choose a subject if data contains multiple
    }
    Returns:
    { "time": [...], "conc": [...],
        "summary": { Cmax, Tmax, AUC, (optional) Cmax_ss, Cmin_ss, Cavg_ss },
        "dosing": [...],
        "fit_from_data"?: { "used": true, "subject": "S01" | "All", "dose_fit": 100.0 }
    }
    """
    model = payload.get("model", "1c")
    route  = payload.get("route", "iv_bolus")
    params = payload.get("params", {})
    dosing = payload.get("dosing", None)
    repeat = payload.get("repeat", None)
    program = payload.get("program", None)
    t_end  = float(payload.get("t_end", 24.0))
    dt     = float(payload.get("dt", 0.1))
    fit_info = None

    try:
        # priority: program > dosing > repeat (legacy)
        if program:
            # Build dosing from program
            program_dosing = expand_program(program, route, params.get("Tinf"))

            # normalize in case expand_program accidentally returns (dosing_list,)
            if isinstance(program_dosing, tuple) and len(program_dosing) == 1 and isinstance(program_dosing[0], list):
                dosing = program_dosing[0]
            else:
                dosing = program_dosing
            repeat = None

        # optionally estimate params from raw data and use them for simulation 
        if (payload.get("estimate_from_data") or payload.get("fit_from_data")) and payload.get("data"):
            df_fit = preprocess_data(pd.DataFrame(payload["data"]))

            # choose subject if specified
            fit_subj = payload.get("fit_subject")
            subj_col = "Subject" if "Subject" in df_fit.columns else ("subject" if "subject" in df_fit.columns else None)
            
            if subj_col:
                uniq = pd.unique(df_fit[subj_col])
                if fit_subj is None and len(uniq) > 1:
                    raise HTTPException(status_code=400,
                        detail=f"Multiple subjects found {uniq.tolist()}. Provide 'fit_subject'.")
                
            if subj_col and fit_subj is not None:
                df_fit = df_fit[df_fit[subj_col] == fit_subj].copy()
            
            t_fit = df_fit["time"].values
            C_fit = df_fit["concentration"].values
            if t_fit.size < 3 or C_fit.size < 3:
                raise HTTPException(status_code=400, detail="Not enough points to fit parameters (need ≥3).")

            # dose for fitting: prefer column, else payload.dose, else 1.0
            if "dose" in df_fit.columns and len(df_fit["dose"]) > 0:
                dose_fit = float(df_fit["dose"].iloc[0])
            else:
                dose_fit = float(payload.get("dose", 1.0))

            # run fit and map to sim params (use macro params for 2c/3c)
            base_params = dict(params)  # preserve F, ka, Tinf, etc.

            if model == "1c":                
                fit = fit_one_compartment(t_fit, C_fit, dose_fit)
                params = {**base_params, "Vd": float(fit["Vd"]), "kel": float(fit["kel"])}
            elif model == "2c":
                fit = fit_two_compartment(t_fit, C_fit, dose_fit)
                params = {**base_params,
                    "A": float(fit["A"]), "alpha": float(fit["alpha"]),
                    "B": float(fit["B"]), "beta": float(fit["beta"])
                }
            elif model == "3c":
                fit = fit_three_compartment(t_fit, C_fit, dose_fit)
                params = {**base_params,
                    "A": float(fit["A"]), "alpha": float(fit["alpha"]),
                    "B": float(fit["B"]), "beta": float(fit["beta"]),
                    "C": float(fit["C"]), "gamma": float(fit["gamma"])
                }
            else:
                raise HTTPException(status_code=400, detail="model must be '1c', '2c', or '3c'")
            
            fit_info = {"used": True, "subject": (str(fit_subj) if fit_subj is not None else ("All" if subj_col else None)), "dose_fit": dose_fit}

        merge_tol = float(payload.get("rate_merge_tol", 0.02))
        if model == "3c" and all(k in params for k in ("A","alpha","B","beta","C","gamma")):
            merged = _maybe_demote_3c_macro(params, tol=merge_tol)

            if merged is not None:
                result = simulate_two_comp_route(
                    route=route, params=merged, dosing=dosing, repeat=repeat, t_end=t_end, dt=dt
                )

                result["note"] = (
                    "Auto-demoted to 2-comp: two 3c rates nearly equal; "
                    "tail merged (equivalent profile)."
                )

                if fit_info:
                    result["fit_from_data"] = {**fit_info, "demoted_to": "2c", "merge_tol": merge_tol}
                return result

        if model == "1c":
            result = simulate_one_comp_route(
                route=route,
                params=params,
                dosing=dosing,
                repeat=repeat,
                t_end=t_end,
                dt=dt
            )

        elif model == "2c":
            result = simulate_two_comp_route(
                route=route,
                params=params,
                dosing=dosing,
                repeat=repeat,
                t_end=t_end,
                dt=dt
            )

        elif model == "3c":
            result = simulate_three_comp_route(
                route=route,
                params=params,
                dosing=dosing,
                repeat=repeat,
                t_end=t_end,
                dt=dt
            )

        else:
            raise HTTPException(status_code=400, detail="model must be '1c', '2c', or '3c'")
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    if fit_info:
        result["fit_from_data"] = fit_info
    return _json_safe(result)

def _run_what_if(payload: dict) -> Dict:
    model  = payload.get("model", "1c")
    route  = payload.get("route", "iv_bolus")
    params = payload.get("params", {})
    weight = float(payload.get("weight_kg", 0.0) or 0.0)
    dose_spec = payload.get("dose_spec", {}) or {}
    tau   = float(payload.get("tau", 0.0) or 0.0)
    count = int(payload.get("count", 0) or 0)
    start = float(payload.get("start", 0.0) or 0.0)
    Tinf  = float(payload.get("Tinf", params.get("Tinf", 0.0) or 0.0))
    t_end = float(payload.get("t_end", 24.0))
    dt    = float(payload.get("dt", 0.1))

    # dose resolution (mg vs mg/kg)
    dose_mg = dose_spec.get("dose_mg")
    dose_mg_per_kg = dose_spec.get("dose_mg_per_kg")
    if dose_mg is None and dose_mg_per_kg is not None:
        if weight <= 0:
            raise HTTPException(status_code=400, detail="dose_mg_per_kg provided but weight_kg is missing/invalid")
        dose_mg = float(dose_mg_per_kg) * weight
    if dose_mg is None:
        raise HTTPException(status_code=400, detail="Provide dose_mg OR (dose_mg_per_kg and weight_kg)")

    # simple optimizer (1c IV bolus only)
    opt = payload.get("optimize")
    if opt and model == "1c" and route == "iv_bolus":
        target = float(opt.get("target_Cmax_ss", 0.0) or 0.0)
        if target > 0 and tau > 0:
            Vd  = float(params.get("Vd", 0.0))
            kel = float(params.get("kel", 0.0))
            if Vd <= 0 or kel <= 0:
                raise HTTPException(status_code=400, detail="Optimizer requires Vd>0 and kel>0 for 1c")
            dose_mg = target * (1.0 - np.exp(-kel * tau)) * Vd

    repeat = {
        "start": start,
        "tau": tau,
        "count": count,
        "dose": dose_mg,
        **({"Tinf": Tinf} if route in ("iv_infusion","oral","sc") and Tinf > 0 else {})
    }

    # simulate
    if model == "1c":
        result = simulate_one_comp_route(route, params, dosing=None, repeat=repeat, t_end=t_end, dt=dt)
    elif model == "2c":
        result = simulate_two_comp_route(route, params, dosing=None, repeat=repeat, t_end=t_end, dt=dt)
    elif model == "3c":
        result = simulate_three_comp_route(route, params, dosing=None, repeat=repeat, t_end=t_end, dt=dt)
    else:
        raise HTTPException(status_code=400, detail="model must be '1c','2c', or '3c'")

    result["what_if"] = {
        "weight_kg": weight or None,
        "dose_mg": dose_mg,
        "dose_mg_per_kg": (float(dose_mg_per_kg) if dose_mg_per_kg is not None else None),
        "tau": tau, "count": count, "Tinf": (Tinf if Tinf > 0 else None)
    }
    return result

@app.post("/what_if")
async def what_if(payload: dict = Body(...)):
    return _json_safe(_run_what_if(payload))

@app.post("/what_if_batch")
async def what_if_batch(payload: dict = Body(...)):
    """
    Run multiple what-if scenarios in one call.
    Body: { "scenarios": [ {payloadLikeWhatIf, "label":"Regimen A"}, ... ] }
    """
    scenarios = payload.get("scenarios", [])
    if not isinstance(scenarios, list) or not scenarios:
        raise HTTPException(status_code=400, detail="Provide non-empty 'scenarios' array")
    out = []
    for i, sc in enumerate(scenarios):
        label = sc.get("label") or f"Scenario {i+1}"
        try:
            res = _run_what_if(sc)
            out.append({"label": label, "ok": True, "result": res})
        except HTTPException as e:
            out.append({"label": label, "ok": False, "error": e.detail})
        except Exception as e:
            out.append({"label": label, "ok": False, "error": str(e)})
    return _json_safe({"results": out})

def _sim(model: str, route: str, params: Dict, dosing, repeat, program, t_end: float, dt: float) -> Dict:
    """
    Minimal dispatcher used by /virtual_trial and other helpers.
    Priority: program > dosing > repeat. Works for 1c/2c/3c and all routes.
    """
    # Expand high-level program → dosing if provided
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
    else:
        raise HTTPException(status_code=400, detail="model must be '1c','2c','3c'")

# ---------- Uncertainty Quantification ----------
@app.post("/uncertainty")
async def uncertainty(payload: dict = Body(...)):
    model = payload.get("model", "1c")
    df = pd.DataFrame(payload["data"])
    df = preprocess_data(df)  # one_comp preprocess handles lowercasing
    t = df["time"].values
    C = df["concentration"].values
    dose = float(payload.get("dose", 1.0))

    # fit once to seed UQ
    if model == "1c":
        fit = fit_one_compartment(t, C, dose)
    elif model == "2c":
        fit = fit_two_compartment(t, C, dose)
    elif model == "3c":
        fit = fit_three_compartment(t, C, dose)
    else:
        raise HTTPException(status_code=400, detail="model must be '1c','2c','3c'")

    method = (payload.get("method") or "bootstrap").lower()
    n = int(payload.get("n", 200))

    if method == "bootstrap":
        out = bootstrap_uq(model, t, C, fit, dose, n_boot=n)
    elif method == "mcmc":
        out = mcmc_uq(model, t, C, fit, dose, n_samples=n)
    else:
        raise HTTPException(status_code=400, detail="method must be 'bootstrap' or 'mcmc'")
    
    # Best-effort summary so the UI can render tables immediately
    def _pick_samples(obj):
        for k in ("samples","draws","bootstrap_samples","posterior_samples","param_draws"):
            v = obj.get(k)
            if isinstance(v, dict):
                return v
        return None

    samples = _pick_samples(out) or {}
    summary = {}

    for name, vals in samples.items():
        try:
            a = np.asarray(vals, dtype=float)
            if a.ndim == 1 and a.size > 1 and np.isfinite(a).all():
                summary[name] = {
                    "mean": float(np.mean(a)),
                    "p05":  float(np.percentile(a, 5)),
                    "p50":  float(np.percentile(a, 50)),
                    "p95":  float(np.percentile(a, 95))
                }
        except Exception:
            pass

    return _json_safe({"fit": fit, "uq": out, "summary": summary})

# ---------- Sensitivity Analysis ----------
@app.post("/sensitivity")
async def sensitivity(payload: dict = Body(...)):
    model = payload.get("model","1c"); route = payload.get("route","iv_bolus")
    params = payload.get("params",{})
    dosing = payload.get("dosing"); repeat = payload.get("repeat"); program = payload.get("program")
    t_end = float(payload.get("t_end", 24.0)); dt = float(payload.get("dt", 0.1))
    metric = payload.get("metric","Cmax")
    method = (payload.get("method") or "local").lower()

    if method == "local":
        vary = payload.get("vary", {k:1 for k in params.keys()})
        out = local_sensitivity(model, route, params, vary, dosing, repeat, program, t_end, dt, metric)
    elif method in ("prcc","global","rank"):
        ranges = payload.get("ranges", {})
        N = int(payload.get("N", 512))
        out = global_prcc_sensitivity(model, route, params, ranges, N, dosing, repeat, program, t_end, dt, metric)
    elif method in ("sobol","saltelli"):
        ranges = payload.get("ranges", {})
        N = int(payload.get("N", 512))
        out = global_sobol_sensitivity(model, route, params, ranges, N, dosing, repeat, program, t_end, dt, metric)
    else:
        raise HTTPException(status_code=400, detail="method must be 'local', 'prcc' or 'sobol'")

    return _json_safe(out)

# ---------- Diagnostics (VPC & residuals) ----------
@app.post("/diagnostics")
async def diagnostics(payload: dict = Body(...)):
    # accept both UI vocab ("one|two|three") and API vocab ("1c|2c|3c")
    model_in = str(payload.get("model", "1c")).lower()
    model_map = {
        "one": "1c", "two": "2c", "three": "3c",
        "1c": "1c", "2c": "2c", "3c": "3c",
    }
    model_key = model_map.get(model_in)
    if model_key is None:
        raise HTTPException(status_code=400, detail="bad model: use 'one|two|three' or '1c|2c|3c'")

    df = pd.DataFrame(payload["data"])
    df = preprocess_data(df)
    t = df["time"].values
    C = df["concentration"].values
    dose = float(payload.get("dose", 1.0))

    if model_key == "1c":
        fit = fit_one_compartment(t, C, dose)
    elif model_key == "2c":
        fit = fit_two_compartment(t, C, dose)
    else:  # "3c"
        fit = fit_three_compartment(t, C, dose)

    buf_res = plot_residuals(t, C, fit, model_key, dose if model_key == "1c" else None)
    buf_vpc = plot_vpc(t, fit, model_key, dose if model_key == "1c" else None, n_draws=int(payload.get("n_draws", 200)))
    res_b64 = base64.b64encode(buf_res.getvalue()).decode("ascii")
    vpc_b64 = base64.b64encode(buf_vpc.getvalue()).decode("ascii")

    return _json_safe({
        "fit": fit,
        "residuals_png_b64": res_b64,
        "vpc_png_b64": vpc_b64
    })

@app.post("/simulate_pk_batch")
async def simulate_pk_batch(payload: dict = Body(...)):
    """
    Run multiple heterogeneous PK sims in one go.
    Body: { "requests": [ { model, route, params, dosing|repeat|program, t_end, dt, label? }, ... ] }
    """
    reqs = payload.get("requests", [])
    if not isinstance(reqs, list) or not reqs:
        raise HTTPException(status_code=400, detail="Provide non-empty 'requests' array")
    out = []
    for i, r in enumerate(reqs):
        label = r.get("label") or f"Sim {i+1}"
        try:
            res = _sim(
                r.get("model","1c"),
                r.get("route","iv_bolus"),
                r.get("params",{}),
                r.get("dosing"),
                r.get("repeat"),
                r.get("program"),
                float(r.get("t_end", 24.0)),
                float(r.get("dt", 0.1))
            )
            out.append({"label": label, "ok": True, "result": res})
        except Exception as e:
            out.append({"label": label, "ok": False, "error": str(e)})
    return _json_safe({"results": out})

# ---------- Virtual Trial ----------
@app.post("/virtual_trial")
async def virtual_trial(payload: dict = Body(...)):
    model = payload.get("model","1c"); route = payload.get("route","iv_bolus")
    base = payload.get("base_params", {})
    dspec = payload.get("param_dists", {})
    dosing = payload.get("dosing"); repeat = payload.get("repeat"); program = payload.get("program")
    t_end = float(payload.get("t_end", 24.0)); dt = float(payload.get("dt", 0.1))
    n = int(payload.get("n_subjects", 200))
    rng = np.random.default_rng()

    def sample_param(name, spec):
        if spec.get("dist","lognormal") == "lognormal":
            m = float(spec["mean"]); cv = float(spec.get("cv", 0.3))
            # lognormal mu, sigma from mean & cv
            sigma = np.sqrt(np.log(1 + cv*cv))
            mu = np.log(m) - 0.5*sigma*sigma
            return float(np.exp(rng.normal(mu, sigma)))
        else:
            lo = float(spec.get("lo", 0.5*base[name])); hi = float(spec.get("hi", 1.5*base[name]))
            return float(lo + (hi - lo) * rng.random())

    sims = []
    t_ref = None

    for _ in range(n):
        p = dict(base)
        for k, sp in dspec.items():
            p[k] = sample_param(k, sp)
        res = _sim(model, route, p, dosing, repeat, program, t_end, dt)
        if t_ref is None:
            t_ref = np.array(res["time"], dtype=float)
        sims.append(np.array(res["conc"], dtype=float))

    M = np.vstack(sims)
    p05 = np.percentile(M, 5, axis=0).tolist()
    p50 = np.percentile(M, 50, axis=0).tolist()
    p95 = np.percentile(M, 95, axis=0).tolist()

    return _json_safe({"time": t_ref.tolist(), "p05": p05, "median": p50, "p95": p95})