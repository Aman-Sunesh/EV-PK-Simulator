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
import numpy as np
import httpx
import io

from .one_compartment_model import (
    preprocess_data,
    fit_one_compartment,
    compute_pk_parameters,
    compute_gof,
    plot_fit
)

from .two_compartment_model import (
    fit_two_compartment,
    compute_pk_parameters_two,
    compute_gof_two,
    plot_fit_two
)

from .reporting import generate_pdf_report

allowed_models = ["one", "two"]
# evpklib.list_studies()
# lab = evpklib.Lab(studies=, data=, method=)

# ---- 
# Helper func
# ----


class Experiment:
    def __init__(self, data, species=None, route = "IV bolus", dose = None,
                 k10 = None, k12 = None, k21 = None, V1 = None, V2 = None):
        """
        Initialize an Experiment object.

        :param data: DataFrame with columns ['time', 'concentration', 'dose', 'Subject'].
        :param model: "one" for one-compartment, "two" for two-compartment.
        :param species: Species of the study (e.g., "human", "rat").
        :param route: Route of administration (default is "IV bolus").
        :param dose: Dose value (optional if data includes dose column).
        :param k10: Optional mechanistic parameter for one-compartment model.
        :param k12: Optional mechanistic parameter for two-compartment model.
        :param k21: Optional mechanistic parameter for two-compartment model.
        :param V1: Optional mechanistic parameter for one-compartment model.
        :param V2: Optional mechanistic parameter for two-compartment model.
        """
        if not isinstance(data, pd.DataFrame):
            raise TypeError("Data must be a pandas DataFrame.")
        if not isinstance(species, (str, type(None))):
            raise TypeError("Species must be a string or None.")
        if not isinstance(route, str):
            raise TypeError("Route must be a string.")
        if not isinstance(dose, (int, float, type(None))):
            raise TypeError("Dose must be a number or None.")
        if k10 is not None and not isinstance(k10, (int, float)):
            raise TypeError("k10 must be a number or None.")
        if k12 is not None and not isinstance(k12, (int, float)):
            raise TypeError("k12 must be a number or None.")
        if k21 is not None and not isinstance(k21, (int, float)):
            raise TypeError("k21 must be a number or None.")
        if V1 is not None and not isinstance(V1, (int, float)):
            raise TypeError("V1 must be a number or None.")
        if V2 is not None and not isinstance(V2, (int, float)):
            raise TypeError("V2 must be a number or None.")
        
        # Initialize attributes
        self.data = preprocess_data(data)
        self.species = species
        self.route = route
        if isinstance(dose, (int, float)):
            self.dose = dose
        elif "dose" in self.data.columns:
            self.dose = self.data["dose"].iloc[0]
        else:
            raise ValueError("Dose must be provided either in the data or as a parameter.")
        
        self.results = None
        self.k10 = k10  # optional mechanistic parameter
        self.k12 = k12  # optional mechanistic parameter
        self.k21 = k21  # optional mechanistic parameter
        self.V1 = V1    # optional mechanistic parameter
        self.V2 = V2    # optional mechanistic parameter

        # Set metadata from the data if available
        if "species" in self.data.columns:
            self.species = self.data["species"].iloc[0]
        if "route" in self.data.columns:
            self.route = self.data["route"].iloc[0]

    # TODO: experiment with xxx len data and metadata 
    def __repr__(self):
        return f"<Experiment with species={self.species} route={self.route} dose={self.dose}>"

    def loadfrom_study(study_id, json_path = "studies_manifest.json", species=None, route = "IV bolus", dose = 1,
                 k10 = None, k12 = None, k21 = None, V1 = None, V2 = None):
        """
        Load an experiment from a study manifest JSON file.
        :param model: "one" for one-compartment, "two" for two-compartment.
        :param study_id: ID of the study to load.
        :param json_path: Path to the JSON manifest file.
        :return: Tuple of (Experiment object, DataFrame).
        """
        if not isinstance(study_id, str):
            raise TypeError("Study ID must be a string.")
        if not isinstance(json_path, str):
            raise TypeError("JSON path must be a string.")
        if not json_path.endswith(".json"):
            raise ValueError("JSON path must end with .json")
        if not isinstance(species, (str, type(None))):
            raise TypeError("Species must be a string or None.")
        if not isinstance(route, str):
            raise TypeError("Route must be a string.")
        if not isinstance(dose, (int, float, type(None))):
            raise TypeError("Dose must be a number or None.")
        if k10 is not None and not isinstance(k10, (int, float)):
            raise TypeError("k10 must be a number or None.")
        if k12 is not None and not isinstance(k12, (int, float)):
            raise TypeError("k12 must be a number or None.")
        if k21 is not None and not isinstance(k21, (int, float)):
            raise TypeError("k21 must be a number or None.")
        if V1 is not None and not isinstance(V1, (int, float)):
            raise TypeError("V1 must be a number or None.")
        if V2 is not None and not isinstance(V2, (int, float)):
            raise TypeError("V2 must be a number or None.")

        with open(json_path) as f:
            manifest = json.load(f)
        entry = next((s for s in manifest if s["id"] == study_id), None)

        if not entry:
            raise Exception("Study not found")

        # fetch CSV from entry["url"]
        resp = httpx.get(entry["url"])
        if resp.status_code != 200:
            raise Exception("Failed to fetch CSV")

        df = pd.read_csv(io.StringIO(resp.text))

        # rename columns to a consistent lowercase keys
        df = df.rename(columns={
            entry["timeColumn"]: "time",
            entry["concColumn"]: "concentration",
            entry["dosingColumn"]: "dose",
            entry["subjectColumn"]: "subject"
        })

        return Experiment(df)
    
    def loadfrom_file(file_path):
        # 1) read into DataFrame
        try:
            if file_path.lower().endswith((".xls", ".xlsx")):
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)
        except Exception as e:
            raise IOError(f"Could not parse file: {e}")
        
        return Experiment(df)
    
    def metadata(self):
        """
        Returns a dictionary of metadata for the experiment.
        """
        return {
            "species": self.species,
            "route": self.route,
            "dose": self.dose,
            "k10": self.k10,
            "k12": self.k12,
            "k21": self.k21,
            "V1": self.V1,
            "V2": self.V2
        }
    
    def list_models():
        """
        Returns a list of available models.
        """
        return allowed_models
    
    def fit(self, model: str = "one"):
        """
        Fit the model to the data.
        
        :param model: "one" for one-compartment, "two" for two-compartment.
        :return: None. Results are avaliable at .results
        """
        
        if model not in allowed_models:
            raise ValueError("Model must be 'one' for one-compartment or 'two' for two-compartment.")
        
        df = self.data
        results = []
        if "subject" in df.columns:
            groups = df.groupby("subject")
        else:
            groups = [("All", df)]

        for subj, grp in groups:
            t      = grp["time"].values
            C      = grp["concentration"].values

            if model == "one":
                fit    = fit_one_compartment(t, C, self.dose)
                pk     = compute_pk_parameters(fit, self.dose)
                gof    = compute_gof(t, C, fit, dose=self.dose)
            elif model == "two":
                fit = fit_two_compartment(t, C, self.dose)  
                pk = compute_pk_parameters_two(fit, self.dose)
                gof       = compute_gof_two(t, C, fit)

            results.append({
                "subject":   subj,
                "model":     model,
                "len":       len(grp),
                "time_min":  grp.time.min(),
                "time_max":  grp.time.max(),
                "t":         t,
                "C":         C,
                "fit":       fit,
                "pk_params": pk,
                "gof":       gof
            })
        self.results = results
    
    def export_report(self, export_path: str):
        # 3) Build a multi-page PDF: one page per Subject (or "All" if no Subject)
        # TODO: check if export_path valid
        if self.results is None:
            raise Exception("No results avaliable, run .fit() first!")

        doc      = SimpleDocTemplate(export_path, pagesize=letter)
        styles   = getSampleStyleSheet()
        elems    = []

        for res in self.results:
            # Apply defaults if user didn’t supply mechanistic parameters
            k10 = self.k10 if self.k10 is not None else 0.1
            k12 = self.k12 if self.k12 is not None else 0.2 
            k21 = self.k21 if self.k21 is not None else 0.05
            V1  = self.V1 if self.V1 is not None else 5.0
            V2  = self.V2 if self.V2 is not None else 20.0
            
            # fit + PK + GOF + plot (branch by model)
            if res["model"] == "one":
                buf_lin, buf_log = plot_fit(res["t"], res["C"], res["fit"], self.dose)
            elif res["model"] == "two":
                try:
                    buf_lin, buf_log, buf_mech = plot_fit_two(
                        res["t"], res["C"], res["fit"], k10, k12, k21, V1, V2)
                except KeyError:
                    # missing mechanistic params → just total‐conc
                    buf_lin, buf_log = plot_fit_two(  # reuse two‐comp plot for total
                        res["t"], res["C"], res["fit"], k10, k12, k21, V1, V2)[:2]
                    buf_mech = None

            # Subject header
            elems.append(Paragraph(f"Subject {res["subject"]}", styles["Title"]))
            elems.append(Spacer(1, 12))

            # Mechanistic central vs. peripheral
            if res["model"] == "two" and buf_mech is not None:
                elems.append(Paragraph("Central vs. Peripheral Compartments", styles["Heading2"]))
                elems.append(Image(buf_mech, width=400, height=200))
                elems.append(Spacer(1, 12))

            # Metadata table
            meta = self.metadata()
            meta["subject"] = res["subject"]
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
                ["Number of points", res["len"]],
                ["Time span (min → max)", f"{res["time_min"]:.2f} → {res["time_max"]:.2f}"]
            ]
            sum_tbl = Table(summary, hAlign="LEFT")
            sum_tbl.setStyle(TableStyle([("GRID", (0,0),(-1,-1), 0.5, colors.grey)]))
            elems.append(Paragraph("Data Summary", styles["Heading2"]))
            elems.append(sum_tbl)
            elems.append(Spacer(1, 12))

            # Fit results (parameters & 95% CI)
            rows = [["Parameter","Estimate","95% CI"]]
            if res["model"] == "one":
                # one-compartment parameters
                for name in ("Vd","kel"):
                    est = res["fit"][name]; ci = res["fit"][f"{name}_ci"]
                    rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
                # derived PK parameters
                for name in ("Cl","t_half","C0","AUC","MRT"):
                    est = res["pk"][name]; ci = res["pk"][f"{name}_ci"]
                    rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])
            elif res["model"] == "two":
                # two-compartment macro parameters
                for name in ("A","alpha","B","beta"):
                    est = res["fit"][name]; ci = res["fit"][f"{name}_ci"]
                    rows.append([name, f"{est:.3g}", f"[{ci[0]:.3g}, {ci[1]:.3g}]"])

                # TODO: check if values are exsistant
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
            gof_data = [["R²", f"{res["gof"]['R2']:.3f}"], ["AIC", f"{res["gof"]['AIC']:.1f}"]]
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

    
# reimplement this when we get manifest from our website
# def list_studies():
#    # load manifest
#    with open("studies_manifest.json") as f:
#        manifest = json.load(f)
#
#    return manifest