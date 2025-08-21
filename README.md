# EV–PK Simulator

A CSV‑first, demotion‑aware pharmacokinetics toolkit for extracellular vesicles (EVs). Fit 1/2/3‑compartment macro‑exponential models, apply principled model selection (AICc + identifiability guards), explore routes/regimens, and export judge‑friendly PDF reports.

> **What’s new?** Three‑compartment support, Route Explorer (IV bolus / IV infusion / Oral / SC), dosing regimens (repeat/program), automatic demotion (3→2, 2→1), and a curated **benchmarks** suite with sample reports.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Repository Structure](#repository-structure)
- [Installation](#installation)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Usage](#usage)
  - [Analyze (fit from data)](#analyze-fit-from-data)
  - [Simulate (route & regimen explorer)](#simulate-route--regimen-explorer)
  - [What‑If & Optimization](#whatif--optimization)
  - [Reports](#reports)
- [Benchmarks: Datasets & Sample Reports](#benchmarks-datasets--sample-reports)
- [Reproducibility & Testing](#reproducibility--testing)
- [Roadmap (Modified Goals)](#roadmap-modified-goals)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**EV–PK Simulator** provides an end‑to‑end PK workflow:

- **Upload** EV concentration–time CSV/Excel (multi‑subject supported)
- **Fit** 1c / 2c / 3c macro‑exponential models
- **Select** models with **AICc** and identifiability guards:
  - relative rate separation `sep_rel` (e.g., α≈β triggers demotion),
  - 3c tail‑AUC fraction threshold (weak γ tail demotes 3→2).
- **Explore** dosing routes and regimens (IV bolus, short IV infusion, oral, SC; repeat/program builder)
- **Export** a comprehensive **PDF** with parameters (and CIs when available), GOF metrics, badges (AICc/ΔAICc, n, demotion reason), and plots.

Built‑in **presets** help you start quickly (e.g., EV (IV, mouse), Small molecule (human)).

---

## Features

- **FastAPI backend** with robust CSV‑first ingestion & preprocessing
- **Macro‑exponential fitting** (1c/2c/3c) with softplus ordering and stability guards
- **Principled model selection** (AIC/AICc, `sep_rel`, tail‑AUC) and **automatic demotion**
- **Route & regimen engine** (IV bolus / short IV infusion / Oral / SC) with repeat/program builder
- **KPIs**: Cmax, Tmax, AUC; steady‑state style metrics where applicable (e.g., Cmax_ss/Cmin_ss)
- **PDF reporting** (ReportLab): tidy tables, clear section headers, linear & semilog plots
- **Lightweight SVG plots** in the UI; semilog toggle
- **Benchmarks**: 10 synthetic CSVs (+ sample reports) to validate selection/demotion behavior

---

## Repository Structure

```
EV-PK-Simulator/
├── backend/
│   ├── main.py                         # API: /upload, /studies, /fit/{1c,2c,3c}, /simulate_pk, /what_if, /report
│   ├── reporting.py                    # PDF generator (ReportLab) with section styles & plots
│   ├── one_compartment_model.py        # 1c fit + helpers
│   ├── two_compartment_model.py        # 2c fit + helpers
│   ├── three_compartment_model.py      # 3c fit + guards (ordered α>β>γ; min gaps; softmax mix)
│   ├── pk_routes_one_comp.py           # Closed-form routes (bolus/infusion/oral/sc) for 1c
│   ├── pk_routes_two_comp.py           # Closed-form routes for 2c (macro↔micro helpers)
│   ├── pk_routes_three_comp.py         # Routes for 3c (macro from micro via eigendecomp)
│   ├── sensitivity.py                  # Local/global sensitivity & variance-based metrics
│   └── uq.py                           # Bootstrap/MCMC (when enabled)
├── frontend/
│   └── src/
│       ├── index.css                   # polished theme; centered headings; unified actions toolbar
│       └── Upload.jsx                  # Analyze/Simulate UI, Route Explorer, dosing builders
└── benchmarks/
    ├── core/
    │   ├── data/                       # 5 core CSVs
    │   └── report/                     # sample PDF reports for each core CSV
    └── addons/
        ├── data/                       # 5 add-on CSVs (stress tests & guardrails)
        └── report/                     # sample PDF reports for each add-on CSV
```

> Folder and filenames may vary slightly across branches; see commit history for the authoritative map.

---

## Installation

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm start
```

The frontend dev server typically runs at `http://localhost:3000` and proxies API calls to `http://localhost:8000` (configure in `package.json` if needed).

---

## Usage

### Analyze (fit from data)

1. **Mode**: choose *One*, *Two*, or *Three* compartment.
2. **Parameter source**: select **Estimate from data (fit)**.
3. **Upload** your CSV (or pick an example study).
4. Click **Fit**. The UI surfaces warnings (e.g., filtered non‑positive concentrations), **AIC/AICc**, **R²**, **ΔAICc**, **n**, and any **demotion reasons**.
5. Optionally enable “use fitted macros” to bridge into Simulate.

### Simulate (route & regimen explorer)

1. **Parameter source**: select **Enter fixed parameters (simulate)**.
2. Choose **route** (IV bolus / IV infusion / Oral / SC).
3. Set model parameters (macro or micro forms).
4. Build a regimen via **Repeat rule**, **Custom schedule**, or **Program builder** (bolus/infusion/repeat).
5. Configure **t_end**, **dt**, and optionally **Semilog Y**; click **Simulate**.

### What‑If & Optimization

- Toggle **mg** vs **mg/kg** (with body weight), adjust τ/count/start/Tinf.
- A simple optimizer (currently for 1c IV bolus) can target **Cmax_ss**.

### Reports

- Click **Download PDF report** to export: metadata, data summary (n, t_min/t_max, Cmax(obs), global t½, |m_early|/|m_late|), fitted parameters (with CIs when available), GOF (AIC/AICc, R²), selection/demotion badges, and plots.

---

## Benchmarks: Datasets & Sample Reports

**Core (5):**

- `pk_1c_ivbolus_clear.csv` (1c wins)
- `pk_2c_biphasic_clear.csv` (2c wins)
- `pk_2c_near_demote.csv` (2c near 1c; demotion favored)
- `pk_3c_triphasic_clear.csv` (3c wins)
- `pk_3c_merged_rates_demote.csv` (3c with α≈β → demote 3→2)

**Add‑ons (5):**

- `pk_3c_weak_tail_demote.csv` (tiny γ tail → demote by tail‑AUC)
- `pk_2c_biphasic_sparse.csv` (n=10 small‑n behavior)
- `pk_1c_ivbolus_noisy.csv` (high noise; parsimony preserved)
- `pk_data_hygiene_issues.csv` (non‑positive C filtered; duplicates aggregated)
- `pk_mgkg_per_row_dose.csv` (per‑row dose/weight; multi‑subject)

Each has a companion **PDF** under `benchmarks/**/report/` that illustrates expected selection, diagnostics, and plots.

---

## Reproducibility & Testing

- Synthetic CSVs are generated with fixed seeds and defined time grids.
- Selection/demotion thresholds: ΔAICc > 2 (prefer simpler), `sep_rel` ≤ 0.05 (rate merge), 3c tail‑AUC < 0.08 (weak tail).
- CI sanity checks: finite estimates, sensible R², correct **n**, stable behavior under sparse/noisy cases.
- Optional executable assertions (per‑CSV) verify picked model, demoter, and the sign/magnitude of ΔAICc.

---

## Roadmap (Modified Goals)

This roadmap aligns with the **Engineering Design Report (In Progress, Aug 21, 2025)**.

**In Progress**
- Injection routes & dosing regimens: short IV infusion (overlap/non‑overlap), Oral/SC with first‑order absorption; steady‑state KPIs.
- PK→PD linkage:
  - **Bacteria CFU**: logistic growth with Hill/Emax kill `k_kill(C)`.
  - **PMM2 rescue via EVs**: Emax/Hill map from C(t) → %Activity.

**Next Up**
- **IVIVE**: scale in‑vitro CL/permeability/binding to in‑vivo PK (CL, Vd).
- **Population variability (Monte Carlo)**: cohort simulation; 5th–95th percentile bands.
- **Nonlinear CL & TMDD**: Michaelis–Menten / target‑mediated options.
- **Optional NCA**: model‑free KPIs (Cmax, Tmax, AUC, MRT, λz).

**Planned**
- Uncertainty: parametric bootstrap; consistent CI badges in UI & PDF.
- Docs: auto‑embed ground‑truth tables from the generator into reports.
- FAIR export: SBML/JSON‑LD, DOIs, ELN/LIMS hooks.

---

## Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit with conventional messages: `git commit -m "feat(module): brief summary"`
4. Push: `git push origin feat/your-feature`
5. Open a PR

Please include tests/bench cases for new selection or demotion logic.

---

## License

MIT — see `LICENSE`.
