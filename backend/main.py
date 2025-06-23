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

        fit       = fit_two_compartment(t, C, dose_i)
        pk_params = compute_pk_parameters_two(fit, dose_i)
        gof       = compute_gof_two(t, C, fit, dose_i)

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
            fit       = fit_two_compartment(t_sub, C_sub, dose_sub)
            pk_params = compute_pk_parameters_two(fit, dose_sub)
            gof       = compute_gof_two(t_sub, C_sub, fit)
            buf_lin, buf_log = plot_fit_two(t_sub, C_sub, fit)
        else:
            fit       = fit_one_compartment(t_sub, C_sub, dose_sub)
            pk_params = compute_pk_parameters(fit, dose_sub)
            gof       = compute_gof(t_sub, C_sub, fit, dose_sub)
            buf_lin, buf_log = plot_fit(t_sub, C_sub, fit, dose_sub)

        # Subject header
        elems.append(Paragraph(f"Subject {subj}", styles["Title"]))
        elems.append(Spacer(1, 12))

        # Metadata table
        meta = payload["metadata"].copy()
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

        # Fit results
        rows = [["Parameter","Estimate","95% CI"]]
        for name in ("Vd","kel"):
            est = fit[name]; ci = fit[f"{name}_ci"]
            rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
        for name in ("Cl","t_half","C0","AUC","MRT"):
            est = pk_params[name]; ci = pk_params[f"{name}_ci"]
            rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
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