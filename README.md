# EV-PK-Simulator

A minimal Streamlit‐based tool for three‐compartment extracellular vesicle (EV) pharmacokinetic simulations.  
Allows users to select injection route, visualize default concentration–time curves, and later fit custom data.

---

## Repository Structure

- `ev_pbpk.py`  Main Streamlit app with ODE solver and UI  
- `venv/`     Python virtual environment (excluded from version control)  
- `README.md`  This file  

---

## Getting Started

1. **Clone repo**  
   ```bash
   git clone https://github.com/Aman-Sunesh/EV-PK-Simulator.git
   cd EV-PK-Simulator

2. **Set up Python environment**
   ```bash
    python3 -m venv venv
    source venv/bin/activate       # (Windows: `.\venv\Scripts\activate`)
    pip install --upgrade pip
    pip install streamlit numpy scipy plotly

3. **Run the app**
   ```bash
    streamlit run ev_pbpk.py


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

## Contributing
1. Fork the repo  
2. Create a feature branch:  
   ```bash
   git checkout -b feature-name



    
