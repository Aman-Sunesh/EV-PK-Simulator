# EV–PK Simulator

_A CSV‑first, demotion‑aware pharmacokinetics toolkit for extracellular vesicles (EVs)._  
Fit 1/2/3‑compartment macro‑exponential models, apply principled model selection (AICc + identifiability guards), explore routes/regimens, link to PD models (bacteria CFU kill and PMM2 activity rescue), and export judge‑friendly PDF reports.

**Live web app:** https://igem.ardabakici.com/  
**Source code:** https://github.com/Aman-Sunesh/EV-PK-Simulator/

> **What’s new?**
> - Three‑compartment support with ordered macro rates (α>β>γ) and stability guards  
> - Route Explorer (IV bolus / short IV infusion / Oral / SC) + dosing **Plan Builder**  
> - Regimen **Compare** (side‑by‑side PK) with KPI readouts (Cmax, Tmax, AUC)  
> - Automatic demotion (3→2, 2→1) via **AICc + rate‑separation + tail‑AUC** guards  
> - Benchmarks suite & sample PDF reports

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Usage](#usage)
  - [Analyze (fit from data)](#analyze-fit-from-data)
  - [Simulate (route & regimen explorer)](#simulate-route--regimen-explorer)
  - [Compare Regimens](#compare-regimens)
  - [Pharmacodynamic (PD) Models](#pharmacodynamic-pd-models)
  - [Reports](#reports)
- [Benchmarks: Datasets & Sample Reports](#benchmarks-datasets--sample-reports)
- [Reproducibility & Testing](#reproducibility--testing)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**EV–PK Simulator** provides an end‑to‑end PK+PD workflow:

- **Upload** EV concentration–time CSV/Excel (multi‑subject supported)  
- **Fit** 1c / 2c / 3c macro‑exponential models  
- **Select** models with **AICc** and identifiability guards:  
  - relative **rate separation** `sep_rel` (e.g., α≈β triggers demotion),  
  - **3c tail‑AUC fraction** threshold (weak γ tail demotes 3→2).
- **Explore** dosing routes and regimens (IV bolus, short IV infusion, oral, SC; repeat/program builder)
- **Link** PK → PD (Bacteria CFU kill; PMM2 activity rescue)
- **Export** PDFs with parameters (and CIs when available), GOF metrics, selection/demotion badges, and plots.

Built‑in **presets** help you start quickly (e.g., EV (IV, mouse), Small molecule (human)).

---

## Features

- **FastAPI** backend with robust CSV‑first ingestion & preprocessing
- **Macro‑exponential fitting** (1c/2c/3c) with softplus ordering and stability guards
- **Principled model selection** (AIC/AICc, `sep_rel`, tail‑AUC) and **automatic demotion**
- **Route & regimen engine** (IV bolus / short IV infusion / Oral / SC) with **Plan Builder**
- **KPIs**: Cmax, Tmax, AUC; steady‑state style metrics where applicable (e.g., Cmax_ss/Cmin_ss)
- **PDF reporting** (ReportLab): tidy tables, clear section headers, linear & semilog plots
- **Lightweight SVG plots** in the UI; **Semilog Y** toggle
- **Benchmarks**: synthetic CSVs (+ sample reports) to validate selection/demotion behavior


---

## Installation

> Prefer the hosted site? Just go to **https://igem.ardabakici.com/**.  
> For local development, follow the steps below.

### Backend

```bash
pip install -r requirements.txt

cd backend
python3 -m venv venv
source venv/bin/activate

# Run FastAPI dev server on http://0.0.0.0:8000
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm start
```

The dev server typically runs at `http://localhost:3000` and proxies API calls to `http://localhost:8000` (configure in `package.json` if needed).

---

## Usage

### Analyze (fit from data)

1. **Mode**: choose *One*, *Two*, or *Three* compartment.  
2. **Parameter source**: select **Estimate from data (fit)**.  
3. **Upload** your CSV (or pick an example study).  
4. Click **Fit**. The UI surfaces warnings (e.g., filtered non‑positive concentrations), **AIC/AICc**, **R²**, **ΔAICc**, **n**, and any **demotion reasons**.  
5. Optionally enable **“Use fitted macros”** to bridge into **Simulate**.

### Simulate (route & regimen explorer)

1. **Parameter source**: **Simulate: Injection Route Explorers & Dosing Regimens**.  
2. Choose **route** (IV bolus / IV infusion / Oral / SC).  
3. Set model parameters (macro or micro forms).  
4. Build a regimen via **Plan Builder** — add **Bolus**, **Infusion**, or **Repeat** rules.  
5. Configure **t_end**, **dt**, and optionally **Semilog Y**; click **Simulate**.

**KPIs** (shown above the plot): `Cmax`, `Tmax`, `AUC (0–t_end)`; at steady state the UI surfaces `Cmax_ss/Cmin_ss` when applicable.

### Compare Regimens

EV–PK Simulator includes a **Compare Regimens** module to benchmark multiple dosing strategies side by side.

- **Upload or select** multiple saved regimen plans (JSON format).
- For each regimen, the simulator computes and overlays:
  - **Plasma concentration curves** across time
  - **AUC**, **C<sub>max</sub>**, **T<sub>max</sub>**, and **residual levels**
  - **PK metrics** (e.g., half-life, steady-state indicators)
- **Interactive plots** support tooltips and legend toggling for clarity.
- Ideal for evaluating:
  - **Route-dependent bioavailability**
  - **Dosing frequency trade-offs**
  - **Tailoring regimens to therapeutic windows**

Use this module to make informed decisions about which regimen achieves **better exposure**, **faster clearance**, or **sustained drug levels**.

### Pharmacodynamic (PD) Models

EV–PK Simulator also supports integrated **PK→PD analysis**, including:

#### PD Analysis from Data

- Upload a CSV with concentration–time values from simulation or experiments.
- Select a **PD model**:
  - **Bacteria CFU Dynamics**: logistic growth + Hill/Emax kill (`k_kill(C)`).
  - **PMM2 Activity Rescue**: saturable Emax/Hill response (`%Activity(C)`).
- Click **Run PD Analysis** to view:
  - Summary stats (e.g., `Initial CFU`, `Final CFU`, `Log Kill`).
  - Plots: `log10 CFU vs time`, `%Activity vs time`.
  - **Download PD Report** (PDF with plots and inputs).

These tools allow **target-attainment queries** (e.g., maintain `%Activity ≥ θ%`) and are suitable for both exploratory work and downstream PD linkage.

### Reports

- Click **Download PDF report** to export: metadata, data summary (n, t_min/t_max, Cmax(obs), global t½, |m_early|/|m_late|), fitted parameters (with CIs when available), GOF (AIC/AICc, R²), selection/demotion badges, and plots.

---

## Benchmarks: Datasets & Sample Reports

**Core (examples):**
- `pk_1c_ivbolus_clear.csv` — 1c wins  
- `pk_2c_biphasic_clear.csv` — 2c wins  
- `pk_2c_near_demote.csv` — 2c near 1c; demotion favored  
- `pk_3c_triphasic_clear.csv` — 3c wins  
- `pk_3c_merged_rates_demote.csv` — 3c with α≈β → demote 3→2

**Add‑ons (examples):**
- `pk_3c_weak_tail_demote.csv` — tiny γ tail → demote by tail‑AUC  
- `pk_2c_biphasic_sparse.csv` — n=10 small‑n behavior  
- `pk_1c_ivbolus_noisy.csv` — high noise; parsimony preserved  
- `pk_data_hygiene_issues.csv` — non‑positive C filtered; duplicates aggregated  
- `pk_mgkg_per_row_dose.csv` — per‑row dose/weight; multi‑subject

Each has a companion **PDF** under `benchmarks/**/report/` that illustrates expected selection, diagnostics, and plots.

---

## Reproducibility & Testing

- Synthetic CSVs are generated with fixed seeds and defined time grids.  
- Selection/demotion thresholds: **ΔAICc > 2** (prefer simpler), `sep_rel ≤ 0.05` (rate merge), **3c tail‑AUC < 0.08** (weak tail).  
- CI sanity checks: finite estimates, sensible R², correct **n**, stable behavior under sparse/noisy cases.  
- Executable assertions (per‑CSV) verify picked model, demoter, and the sign/magnitude of ΔAICc.

---

## Contributing

1. Fork the repo  
2. Create a feature branch: `git checkout -b feat/your-feature`  
3. Commit with conventional messages: `git commit -m "feat(module): brief summary"`  
4. Push: `git push origin feat/your-feature`  
5. Open a PR

---

## License

MIT — see `LICENSE`.
