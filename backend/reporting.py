# ReportLab imports for PDF generation
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
import uuid
import pandas as pd
from io import BytesIO

# =============================================================================
# Report Generation
# =============================================================================

def generate_pdf_report(
    metadata: dict,
    df: pd.DataFrame,
    fit: dict,
    pk_params: dict,
    gof: dict,
    plot_buffer_lin: BytesIO,   
    plot_buffer_log: BytesIO,  
    output_path: str
):
    """
    Create a PDF report including:
      - Study metadata
      - Data summary (n points, time span)
      - Fit results table (Vd, Cl, kel, t_half, AUC, MRT + 95% CI)
      - Goodness-of-fit metrics (R2, AIC)
      - Plot (linear + semilog)
    
    Args:
      metadata: {'study_id', 'species', 'route', 'dose'}
      df: preprocessed DataFrame with 'time' & 'concentration'
      fit: output of fit_one_compartment (incl. CI & pcov)
      pk_params: output of compute_pk_parameters
      gof: output of compute_gof
      plot_buffer: BytesIO containing our two-up PNG (see below)
      output_path: filesystem path to write the PDF
    """
    # 1) Prepare document
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    elems = []

    # 2) Title
    elems.append(Paragraph(f"EV-Portal PK Report: Study {metadata.get('study_id','-')}", styles['Title']))
    elems.append(Spacer(1, 12))

    # 3) Metadata section
    elems.append(Paragraph("Study Metadata", styles['Heading2']))
    meta_data = [[k, str(v)] for k, v in metadata.items()]
    meta_tbl = Table(meta_data, hAlign='LEFT')
    meta_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    elems.append(meta_tbl)
    elems.append(Spacer(1, 12))

    # 4) Data summary
    elems.append(Paragraph("Data Summary", styles['Heading2']))
    n = len(df)
    t_min, t_max = df['time'].min(), df['time'].max()
    summary_data = [
        ["Number of points", n],
        ["Time span (min → max)", f"{t_min:.2f} → {t_max:.2f}"]
    ]
    sum_tbl = Table(summary_data, hAlign='LEFT')
    sum_tbl.setStyle(TableStyle([('GRID', (0,0),(-1,-1), 0.5, colors.grey)]))
    elems.append(sum_tbl)
    elems.append(Spacer(1, 12))

    # 5) Fit results table
    elems.append(Paragraph("Fit Results (with 95% CI)", styles['Heading2']))
    fit_rows = [
        ["Parameter", "Estimate", "95% CI"]
    ]
    # Vd & kel
    for name in ['Vd','kel']:
        est = fit[name]
        ci  = fit[f"{name}_ci"]
        fit_rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
    # Derived PK params
    for name in ['Cl','t_half','C0','AUC','MRT']:
        est = pk_params[name]
        ci  = pk_params[f"{name}_ci"]
        fit_rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])

    fit_tbl = Table(fit_rows, hAlign='LEFT')
    fit_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), colors.lightgrey),
        ('GRID', (0,0),(-1,-1), 0.5, colors.grey),
    ]))
    elems.append(fit_tbl)
    elems.append(Spacer(1, 12))

    # 6) Goodness-of-fit
    elems.append(Paragraph("Goodness-of-Fit", styles['Heading2']))
    gof_data = [
        ["R²", f"{gof['R2']:.3f}"],
        ["AIC", f"{gof['AIC']:.1f}"]
    ]
    gof_tbl = Table(gof_data, hAlign='LEFT')
    gof_tbl.setStyle(TableStyle([('GRID', (0,0),(-1,-1), 0.5, colors.grey)]))
    elems.append(gof_tbl)
    elems.append(Spacer(1, 12))

    # 7) Plots: linear then semilog
    elems.append(Paragraph("Concentration vs. Time (Linear)", styles['Heading2']))
    img_lin = Image(plot_buffer_lin, width=400, height=200)
    elems.append(img_lin)
    elems.append(Spacer(1, 12))

    elems.append(Paragraph("Concentration vs. Time (Semilog)", styles['Heading2']))
    img_log = Image(plot_buffer_log, width=400, height=200)
    elems.append(img_log)

    # 8) Build PDF
    doc.build(elems)

    return output_path