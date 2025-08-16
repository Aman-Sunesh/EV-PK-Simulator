from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    Image, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from typing import List, Any
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

from reporting import generate_pdf_report
from pk_routes_one_comp import simulate_one_comp_route

app = FastAPI()

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
    df.rename(columns={c.lower(): c for c in df.columns}, inplace=True)

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
    resp = httpx.get(entry["url"])
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch CSV")

    df = pd.read_csv(io.StringIO(resp.text))

    # rename columns to a consistent lowercase keys
    df = df.rename(columns={
        entry["timeColumn"]: "time",
        entry["concColumn"]: "concentration",
        entry["dosingColumn"]: "dose",
        entry["subjectColumn"]: "Subject"
    })
    return df.to_dict(orient="records")


@app.post("/fit/one_compartment")
async def fit_one(payload: dict):
    # build a DataFrame from the incoming JSON
    df = pd.DataFrame(payload.get("data", []))

    results: List[Any] = []
    
    # Always produce a results list, grouped by Subject if present
    if "Subject" in df.columns:
        groups = df.groupby("Subject")
    else:
        groups = [("All", df)]

    for subj, grp in groups:
        t      = grp["time"].values
        C      = grp["concentration"].values
        
        if "dose" in grp.columns:
            dose_i = float(grp["dose"].iloc[0])
        else:
            dose_i = float(payload.get("dose", 1.0))

        fit    = fit_one_compartment(t, C, dose_i)
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
    results = []
    if "Subject" in df.columns:
        groups = df.groupby("Subject")
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
    out_path = "/tmp/ev_pk_report.pdf"
    doc      = SimpleDocTemplate(out_path, pagesize=letter)
    styles   = getSampleStyleSheet()
    elems    = []

    if "Subject" in df.columns:
        groups = df.groupby("Subject")
    else:
        groups = [("All", df)]

    for subj, grp in groups:
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

            try:
                buf_lin, buf_log, buf_mech = plot_fit_two(
                    t_sub, C_sub, fit, k10, k12, k21, V1, V2)
            except KeyError:
                # missing mechanistic params → just total‐conc
                buf_lin, buf_log = plot_fit_two(  # reuse two‐comp plot for total
                    t_sub, C_sub, fit,
                    k10, k12, k21, V1, V2
                )[:2]
                buf_mech = None

        else:
            fit       = fit_one_compartment(t_sub, C_sub, dose_sub)
            pk_params = compute_pk_parameters(fit, dose_sub)
            gof       = compute_gof(t_sub, C_sub, fit)
            buf_lin, buf_log = plot_fit(t_sub, C_sub, fit, dose_sub)

        # Subject header
        elems.append(Paragraph(f"Subject {subj}", styles["Title"]))
        elems.append(Spacer(1, 12))

        # Mechanistic central vs. peripheral
        if model == "two" and buf_mech is not None:
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
        if payload["metadata"].get("model","one") == "one":
            # one-compartment parameters
            for name in ("Vd","kel"):
                est = fit[name]; ci = fit[f"{name}_ci"]
                rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
            # derived PK parameters
            for name in ("Cl","t_half","C0","AUC","MRT"):
                est = pk_params[name]; ci = pk_params[f"{name}_ci"]
                rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
        else:
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

        # Plots: linear & semilog
        elems.append(Paragraph("Linear Fit", styles["Heading2"]))
        elems.append(Image(buf_lin, width=400, height=200))
        elems.append(Spacer(1, 12))
        elems.append(Paragraph("Semilog Fit", styles["Heading2"]))
        elems.append(Image(buf_log, width=400, height=200))

        # page break
        elems.append(PageBreak())

    # write out the PDF
    doc.build(elems)
    return FileResponse(
        out_path,
        media_type="application/pdf",
        filename="EVPK_Report.pdf"
    )

+@app.post("/simulate_pk")
+async def simulate_pk(payload: dict = Body(...)):
    """
    One-compartment simulation for multiple dosing routes.
    Body:
    {
      "model": "1c",
      "route": "iv_bolus" | "iv_infusion" | "oral" | "sc",
      "params": {
        "Vd": float,
        "kel": float,
        "F": float?,       // oral/sc
        "ka": float?,      // oral/sc
        "Tinf": float?     // infusion default if not per-dose
      },
      // EITHER an explicit dose schedule...
      "dosing": [ { "time": float, "dose": float, "Tinf": float? }, ... ],
      // ...OR a simple repeat rule to generate dosing on the backend
      "repeat": { "start": 0.0, "tau": 8.0, "count": 10, "dose": 100.0, "Tinf": 1.0? },
      // time grid
      "t_end": 24.0,
      "dt": 0.1
    }
    Returns:
      { "time": [...], "conc": [...], "summary": { Cmax, Tmax, AUC, (optional) Cmax_ss, Cmin_ss } }
    """
    model = payload.get("model", "1c")
    if model != "1c":
        raise HTTPException(status_code=400, detail="Only '1c' model supported in /simulate_pk for now.")
    route  = payload.get("route", "iv_bolus")
    params = payload.get("params", {})
    dosing = payload.get("dosing", None)
    repeat = payload.get("repeat", None)
    t_end  = float(payload.get("t_end", 24.0))
    dt     = float(payload.get("dt", 0.1))

    try:
        result = simulate_one_comp_route(
            route=route,
            params=params,
            dosing=dosing,
            repeat=repeat,
            t_end=t_end,
            dt=dt
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result