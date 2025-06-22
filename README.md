# EV-Portal

A web-based end-to-end platform for extracellular vesicle (EV) pharmacokinetics (PK) and data analysis. Upload raw concentration–time data, fit one- or two-compartment models, and download comprehensive PDF reports—all in under five minutes.

## Table of Contents

- [Overview](#overview)  
- [Features](#features)  
- [Repository Structure](#repository-structure)  
- [Installation](#installation)  
  - [Backend](#backend)  
  - [Frontend](#frontend)  
- [Usage](#usage)
- [Upcoming Tasks](#upcoming-Tasks)  
- [Contributing](#contributing)  
- [License](#license)  

---

## Overview

EV-Portal allows users to:

- Upload EV concentration–time data (CSV/Excel)  
- Browse built-in example studies  
- Fit one- and two-compartment PK models  
- Visualize concentration–time curves and fit diagnostics  
- Generate downloadable PDF reports  

---

## Features

- **FastAPI Backend** for data ingestion, model fitting, and report generation  
- **SQLite + SQLAlchemy** for lightweight data storage  
- **Matplotlib** integration for plotting PK curves  
- **ReportLab** for PDF report creation  
- **React Frontend** for a responsive user interface  
- **In-memory & on-disk caching** of example studies  

---


## Repository Structure

```bash
ev-portal/
├── backend/                            # FastAPI server and PK modeling code
│   ├── main.py                         # API endpoints: /upload, /fit/one_compartment, /report, /studies
│   ├── database.py                     # SQLAlchemy setup for SQLite
│   ├── models.py                       # ORM models: Study, UserUpload, PKModelResult
│   ├── one_compartment_model.py        # PK fitting functions & plotting
│   ├── reporting.py                    # PDF report generator using ReportLab
│   └── studies_manifest.json           # Example studies library manifest
└── frontend/                           # React app
    ├── package.json                    # dependencies, proxy to backend
    ├── public/
    │   └── index.html
    └── src/
        ├── index.js
        ├── index.css                   # global styles
        ├── App.js
        └── Upload.jsx                  # CSV upload, preview, fit, report UI
```
---

## Installation

### Backend

1. **Create & activate virtual environment**  
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   ```
   
2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```


3. **Run the server**
   ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

### Frontend

1. **Install dependencies**  
   ```bash
   cd frontend
   npm install
   ```
   
2. **Install dependencies**
   ```bash
   npm start
   ```

---

## Usage

1. Open your browser at `http://localhost:3000`
2. Upload a CSV/Excel file or select an example study
3. Click **Fit Model** to run a one-compartment PK fit
4. View plots and download the PDF report

---

## Upcoming Tasks

- **Two-Compartment PK Model**  
  Extend the fitting backend and UI to handle a central–peripheral compartment (V₁, V₂, k₁₂, k₂₁, kₑₗ).

- **Injection-Route Explorer**  
  Add route selection (IV bolus, IV infusion, SC, IM), simulate absorption kinetics (ka/Tinf) and plot C–time profiles.

- **Modular PBPK Models**  
  Define organ-level ODEs (liver, kidney, muscle, etc.), expose parameters in the backend and stub the UI for organ configuration.

- **IVIVE Module**  
  Scale in vitro clearance/permeability data to whole-body PK (CL, Vd), integrate input panels and include results in the PDF report.

- **PK→PD Integration**  
  Couple PK curves to a bacterial-kill PD model (Eₘₐₓ/EC₅₀), add dual-panel plotting and UI controls for PD parameters.

- **Dosing Regimen Builder**  
  Interactive UI to assemble bolus/infusion/multiple‐dose schedules, simulate regimens, and compare exposure metrics.

- **Population Variability & Monte Carlo**  
  Simulate virtual cohorts sampling PK/PD parameters from distributions and display percentile bands (e.g., 5th–95th).

- **Deployment & Collaboration**  
  Dockerize front-end and back-end, set up CI/CD, and enable shareable session links for team collaboration.

- **Advanced Systems-Biology Plugins**  
  Create a plugin framework for immune or signaling pathway ODE modules (e.g., NFκB), with drag-and-drop UI stubs.

- **Real-Time Interactive Simulation**  
  Port the ODE solver to WebAssembly or a background worker for instant parameter tweaking and live feedback.

- **Data Export & FAIR Integration**  
  One-click export to SBML/JSON-LD, embed DOIs, and link to ELN/LIMS for reproducible publishing.

- **AI-Guided Modeling Assistant**  
  Embed a natural-language chat interface to guide users through data upload, model choice, interpretation, and next-step suggestions.

---

## Contributing

1. Fork the repository  
2. Create a feature branch (`git checkout -b feature/your-feature`)  
3. Commit your changes (`git commit -m "Add your feature"`)  
4. Push to your branch (`git push origin feature/your-feature`)  
5. Open a Pull Request  

Please follow the existing code style and add tests for new functionality.

---

## License

This project is licensed under the MIT License. See `LICENSE` for details.

---    
