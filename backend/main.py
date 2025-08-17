from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    Image, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet
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

    return {
      "preview": preview,
     "data": full,
      "warnings": warnings
    }

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

    # detect subject column once, accept either 'Subject' or 'subject'
    subj_col = "Subject" if "Subject" in df.columns else ("subject" if "subject" in df.columns else None)

    results: List[Any] = []

    # group by subject if present, otherwise single "All" group
    groups = df.groupby(subj_col) if subj_col else [("All", df)]

    for subj, grp in groups:
        g = preprocess_data(grp.copy())     # <- use your existing helper
        t = g["time"].values
        C = g["concentration"].values
            
        if "dose" in grp.columns:
            dose_i = float(grp["dose"].iloc[0])
        else:
            dose_i = float(payload.get("dose", 1.0))

        try:
            fit = fit_one_compartment(t, C, dose_i)
        except RuntimeError as e:
            # turn into a clean HTTP 400
            raise HTTPException(status_code=400, detail=str(e))

        if isinstance(fit.get("pcov"), np.ndarray):
            fit["pcov"] = fit["pcov"].tolist()

        pk     = compute_pk_parameters(fit, dose_i)
        gof    = compute_gof(t, C, fit, dose_i)

        results.append({
            "subject":   subj,
            "fit":       fit,
            "pk_params": pk,
            "gof":       gof
        })

    return {"results": results}

@app.post("/fit/two_compartment")
async def fit_two(payload: dict):
    df = pd.DataFrame(payload.get("data", []))
    df.columns = [c.strip() for c in df.columns]            
    has_subject = "Subject" in df.columns or "subject" in df.columns
    subj_col = "Subject" if "Subject" in df.columns else ("subject" if "subject" in df.columns else None)    
    
    results = []
   
    if subj_col:
        groups = df.groupby(subj_col)
    else:
        groups = [("All", df)]

    for subj, grp in groups:
        t      = grp["time"].values
        C      = grp["concentration"].values
        dose_i = float(grp["dose"].iloc[0]) if "dose" in grp.columns else float(payload.get("dose", 1.0))

        try:
            fit = fit_two_compartment(t, C, dose_i)
        except RuntimeError as e:
            # turn into a clean HTTP 400
            raise HTTPException(status_code=400, detail=str(e))
        
        pk_params = compute_pk_parameters_two(fit, dose_i)
        gof       = compute_gof_two(t, C, fit)

        results.append({
            "subject":   subj,
            "fit":       fit,
            "pk_params": pk_params,
            "gof":       gof
        })
    return {"results": results}

@app.post("/fit/three_compartment")
async def fit_three(payload: dict):
    df = pd.DataFrame(payload.get("data", []))
    df.columns = [c.strip() for c in df.columns]
    subj_col = "Subject" if "Subject" in df.columns else ("subject" if "subject" in df.columns else None)
    results = []
    groups = df.groupby(subj_col) if subj_col else [("All", df)]

    for subj, grp in groups:
        t = grp["time"].values
        C = grp["concentration"].values
        dose_i = float(grp["dose"].iloc[0]) if "dose" in grp.columns else float(payload.get("dose", 1.0))
        n = len(t)

        # try 3c
        try:
            fit3 = fit_three_compartment(t, C, dose_i)
            gof3 = compute_gof_three(t, C, fit3)
        except RuntimeError as e:
            # if 3c fails outright, surface error (UI/report already has fallback paths)
            raise HTTPException(status_code=400, detail=str(e))

        # fit 2c for model selection guardrail
        try:
            fit2 = fit_two_compartment(t, C, dose_i)
            gof2 = compute_gof_two(t, C, fit2)
            # AICc(2c)
            k2 = 4
            AICc2 = gof2["AIC"] + (2*k2*(k2+1))/max(n - k2 - 1, 1) if n > (k2 + 1) else float('inf')
        except Exception:
            fit2, gof2, AICc2 = None, None, float('inf')

        # AICc(3c)
        AICc3 = gof3.get("AICc")
        if AICc3 is None or not np.isfinite(AICc3):
            k3 = 6
            AICc3 = gof3["AIC"] + (2*k3*(k3+1))/max(n - k3 - 1, 1) if n > (k3 + 1) else float('inf')

        # separation + tail strength guard (scale-invariant & amplitude-aware)
        sep_log   = float(gof3.get("rate_sep_log", np.nan))
        tail_frac = float(gof3.get("tail_auc_frac", np.nan))
        bad_sep   = (not np.isfinite(sep_log)) or (sep_log < np.log(1.5))   # < ~0.405
        weak_tail = (not np.isfinite(tail_frac)) or (tail_frac < 0.08)      # < 8% of AUC

        # Demote only if: too few points, OR 3c not clearly better by AICc, OR BOTH (near-degenerate AND negligible tail)
        demote = (n < 8) or not (AICc3 + 2 < AICc2) or (bad_sep and weak_tail)

        if demote and (fit2 is not None):
            pk_params = compute_pk_parameters_two(fit2, dose_i)
            results.append({
                "subject": subj,
                "fit": fit2,
                "pk_params": pk_params,
                "gof": {**gof2, "AICc": float(AICc2)},
                "note": "Auto-demoted to 2-comp: ΔAICc<2 and/or poor rate separation or n<8."
            })
        else:
            pk_params = compute_pk_parameters_three(fit3, dose_i)
            results.append({
                "subject": subj,
                "fit": fit3,
                "pk_params": pk_params,
                "gof": gof3
            })
    return {"results": results}

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
    elems    = []

    subj_col = "subject" if "subject" in df.columns else ("Subject" if "Subject" in df.columns else None)
    groups = list(df.groupby(subj_col)) if subj_col else [("All", df)]

    for idx, (subj, grp) in enumerate(groups):
        mdl_for_page = model

        # preprocess this subject
        df_sub = preprocess_data(grp[["time", "concentration"]].copy())
        t_sub  = df_sub["time"].values
        C_sub  = df_sub["concentration"].values

        # if the DataFrame itself has a dose column, use it; otherwise fall back to metadata.dose
        if "dose" in grp.columns:
            dose_sub = float(grp["dose"].iloc[0])
        else:
            dose_sub = float(payload["metadata"]["dose"])

        # fit + PK + GOF + plot (branch by model)
        if model == "two":
            fit         = fit_two_compartment(t_sub, C_sub, dose_sub)
            pk_params   = compute_pk_parameters_two(fit, dose_sub)
            gof         = compute_gof_two(t_sub, C_sub, fit)

            # only draw mechanistic if all params are present
            md = payload["metadata"]

            # Apply defaults if user didn’t supply mechanistic parameters
            k10 = float(md.get("k10", 0.1))
            k12 = float(md.get("k12", 0.2))
            k21 = float(md.get("k21", 0.05))
            V1  = float(md.get("V1",  5.0))
            V2  = float(md.get("V2", 20.0))

            meta_events = payload["metadata"].get("dosing", None)
            dosing_events = meta_events if meta_events else [{"time": 0.0, "dose": dose_sub, **(
                {"Tinf": float(payload["metadata"].get("Tinf", 0.0))} if payload["metadata"].get("Tinf") else {}
            )}]

            buf_lin, buf_log, buf_mech, buf_dose = plot_fit_two(
                t_sub, C_sub, fit, k10, k12, k21, V1, V2, dosing=dosing_events)

        elif model == "three":
            try:
                if len(t_sub) < 7:
                    raise RuntimeError("Too few points for a stable three-compartment fit; using 2c.")

                # --- fit 3-comp and compute GOF on log-scale ---
                fit3 = fit_three_compartment(t_sub, C_sub, dose_sub)
                gof3 = compute_gof_three(t_sub, C_sub, fit3)

                # --- also fit 2-comp for model selection guardrail ---
                fit2 = fit_two_compartment(t_sub, C_sub, dose_sub)
                gof2 = compute_gof_two(t_sub, C_sub, fit2)

                # --- AICc and rate-separation checks ---
                n = len(t_sub); k2, k3 = 4, 6
                AICc2 = gof2["AIC"] + (2*k2*(k2+1))/max(n - k2 - 1, 1) if n > (k2 + 1) else float('inf')
                AICc3 = gof3.get("AICc")
                if AICc3 is None or not np.isfinite(AICc3):
                    AICc3 = gof3["AIC"] + (2*k3*(k3+1))/max(n - k3 - 1, 1) if n > (k3 + 1) else float('inf')
                    
                sep_log   = float(gof3.get("rate_sep_log", np.nan))
                tail_frac = float(gof3.get("tail_auc_frac", np.nan))
                bad_sep   = (not np.isfinite(sep_log)) or (sep_log < np.log(1.5))
                weak_tail = (not np.isfinite(tail_frac)) or (tail_frac < 0.08)
                use_two   = (n < 8) or not (AICc3 + 2 < AICc2) or (bad_sep and weak_tail)


                md = payload["metadata"]
                if use_two:
                    mdl_for_page = "two"
                    elems.append(Paragraph(
                        f"Note: Auto-demoted to two-compartment for Subject {subj} "
                        f"(ΔAICc<2 and/or poor rate separation or n<8).", styles["Italic"]))
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

        # Mechanistic central vs. peripheral
        if model in ("two","three") and buf_mech is not None:
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

        # Data summary
        summary = [
            ["Number of points", len(df_sub)],
            ["Time span (min → max)", f"{df_sub.time.min():.2f} → {df_sub.time.max():.2f}"]
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
        gof_tbl  = Table(gof_data, hAlign="LEFT")
        gof_tbl.setStyle(TableStyle([("GRID", (0,0),(-1,-1), 0.5, colors.grey)]))
        elems.append(Paragraph("Goodness-of-Fit", styles["Heading2"]))
        elems.append(gof_tbl)
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
        elems.append(Paragraph("Linear Fit", styles["Heading2"]))
        elems.append(Image(buf_lin, width=400, height=200))
        elems.append(Spacer(1, 12))
        elems.append(Paragraph("Semilog Fit", styles["Heading2"]))
        elems.append(Image(buf_log, width=400, height=200))
        elems.append(Spacer(1, 12))
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
    }
    Returns:
    { "time": [...], "conc": [...],
        "summary": { Cmax, Tmax, AUC, (optional) Cmax_ss, Cmin_ss, Cavg_ss },
        "dosing": [...]
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result

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
    return _run_what_if(payload)

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
    return {"results": out}

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

    return {"fit": fit, "uq": out, "summary": summary}

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

    return out

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

    return {
        "fit": fit,
        "residuals_png_b64": res_b64,
        "vpc_png_b64": vpc_b64
    }

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
    return {"results": out}

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

    return {"time": t_ref.tolist(), "p05": p05, "median": p50, "p95": p95}