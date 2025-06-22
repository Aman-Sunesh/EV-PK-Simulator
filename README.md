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

### Step 1: Basic ODE Solver Prototype
- Implements a three‐compartment ODE system (blood ⇄ tissue → clearance) with hard‐coded rate constants (`k12=0.30, k21=0.10, kel=0.50`).
- Plots C₁ (blood), C₂ (tissue), and C₃ (cleared) vs. time (0–24 h).

### Step 2: Route Selector + Initial Conditions
- **Dropdown to choose injection route:**
  - **Intravenous (IV):**
    - `C1(0)=100, C2(0)=0, C3(0)=0`
    - `(k12=0.30, k21=0.10, kel=0.50)`
  - **Subcutaneous (SC):**
    - `C4(0)=100` (depot), `C1(0)=0, C2(0)=0, C3(0)=0`
    - `(k12=0.20, k21=0.08, kel=0.60, kab=0.15)`
    - Implements a 4th ODE for depot → blood absorption at `kab`.
  - **Intratumoral:**
    - `C2(0)=100, C1(0)=0, C3(0)=0`
    - `(k12=0.25, k21=0.07, kel=0.55)`
- Automatically sets initial conditions and rate constants per route.
- Plots blood, tissue, and clearance compartments; if SC, also shows depot decay.


### Step 3: Data Upload & Curve Fitting
- Add file uploader (CSV of concentration vs. time).
- Perform least‐squares optimization to fit `(k12, k21, kel, kab)` to user data.
- Overlay fitted curve vs. raw data.

### Step 4: What‐If Analyses
- Let users adjust rate constants manually.
- Simulate multiple chassis types (e.g., exosome vs. liposome).
- Compare different injection routes side‐by‐side.

### Step 5: Injection Site Recommendation Module
- Based on target tissue concentration and desired clearance, suggest optimal route & dosing.
- Simple rule‐based suggestions using default or fitted parameters.

### Step 6: Documentation & Examples
- Provide sample CSV datasets for tutorial.
- Write usage guide with screenshots.

---

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
