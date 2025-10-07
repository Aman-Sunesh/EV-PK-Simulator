# PD Test Datasets and Validation Guide

This document summarizes the PD test datasets added for quick functional and regression testing of the PD analysis features (bacterial CFU dynamics and PMM2 rescue activity).

## Purpose
These datasets are small, human-readable CSVs intended to:
- Provide deterministic PK inputs (time-concentration series) for PD endpoints.
- Provide an accompanying set of expected outputs (time-series) to validate that PD implementations produce qualitatively correct results and that UI/report formatting is stable.

## Files added
All files live under `./data/`.

Input CSVs (PK + PD params, 3 subjects each):
- `pd_bacteria_baseline.csv` — bacteria: CFU0=1e6, k_max=0.5, EC50=2.0, hill=1.0, k_grow=0.1
- `pd_bacteria_high_kmax.csv` — bacteria: same as baseline but k_max=1.0
- `pd_bacteria_low_kmax.csv` — bacteria: same as baseline but k_max=0.2
- `pd_pmm2_baseline.csv` — PMM2: Emax=90, EC50=1.0, hill=1.0, Emin=10
- `pd_pmm2_high_ec50.csv` — PMM2: Emax=90, EC50=5.0 (less potent)
- `pd_pmm2_high_emax.csv` — PMM2: Emax=100, EC50=1.0 (higher ceiling)

Expected-result CSVs (approximate targets per time provided):
- `expected_pd_bacteria_baseline.csv`
- `expected_pd_bacteria_high_kmax.csv`
- `expected_pd_bacteria_low_kmax.csv`
- `expected_pd_pmm2_baseline.csv`
- `expected_pd_pmm2_high_ec50.csv`
- `expected_pd_pmm2_high_emax.csv`

## CSV column descriptions
Inputs (both bacteria and PMM2 CSVs use these core columns):
- `time` — time after dose (hours)
- `concentration` — drug concentration at `time` (units consistent with PD params)
- `subject` — subject identifier
- `pd_model` — PD model to be used

Bacteria-specific PD columns included per-row (present in bacteria CSVs):
- `CFU0`, `k_max`, `EC50`, `hill`, `k_grow`

PMM2-specific PD columns included per-row (present in PMM2 CSVs):
- `Emax`, `EC50`, `hill`, `Emin`

## PD model references (implementation used in repo)
- Bacteria CFU (link to code: `backend/pd_models.py`)
  - $k_{kill}(C) = k_{max} * C^{hill} / (EC50^{hill} + C^{hill})$
  - $dCFU/dt = (k_{grow} - k_{kill}(C)) * CFU$
  - Numerical integration is performed in the repo by stepping across the time points and applying the local $kill/growth$ for each $dt$.

- PMM2 rescue ($Hill/E_{max}$)
  - $Activity\% = E_{min} + (E_{max} - E_{min}) * C^{hill} / (EC_{50}^{hill} + C^{hill})$
  - Computed pointwise for each $C(t)$.

## How to run the tests (frontend or API)
1. Upload one of the PD CSVs using the frontend Upload UI.
2. Use the PD UI to choose the appropriate PD model (Bacteria CFU or PMM2) and enter the hyperparameters (e.g. `CFU0`, `k_max`, `Emax`, `EC50`) denoted in CSV file.

## Evaluation metrics & acceptance criteria
Following are the expected results for the given PD CSVs.

Acceptance criterions (per-subject; for our three bacteria test files):
- `pd_bacteria_baseline.csv` (k_max = 0.5): clear multi-log reduction, subject-level differences expected.
  - Subj01 (C0 ≈ 10): final CFU ~10^4–10^5, log-kill ≈ 1.0. PASSED
  - Subj02 (C0 ≈ 8): final CFU somewhat higher ~10^6, log-kill < 1. PASSED
  - Subj03 (C0 ≈ 12): final CFU somewhat lower ~10^4–10^5, log-kill > 1. PASSED

- `pd_bacteria_high_kmax.csv` (k_max = 1.0): expected near-eradication for all subjects; final CFU should be extremely low.
  - Subj01 (C0 ≈ 10): final CFU ≪ 10^2, log-kill > 4. PASSED
  - Subj02 (C0 ≈ 8): final CFU ≪ 10^3, log-kill > 3. PASSED
  - Subj03 (C0 ≈ 12): final CFU ≪ 10^2, log-kill > 5. PASSED

- `pd_bacteria_low_kmax.csv` (k_max = 0.2): little or no kill; possible net growth.
  - Subj01 (C0 ≈ 10): final CFU > CFU0; log-kill < 0. PASSED
  - Subj02 (C0 ≈ 8): final CFU > CFU0; log-kill < 0. PASSED
  - Subj03 (C0 ≈ 12): final CFU > CFU0; log-kill < 0. PASSED

For PMM2 (percent activity) — metrics to compute per subject:
- Peak %Activity (maximum over time)
- AUC of %Activity over time (numerical trapezoid on time-activity curve)
- Time above threshold (e.g., time where activity >= 50%) — useful for pharmacodynamic durability checks

Acceptance expectations (per-subject; our three PMM2 files):
- `pd_pmm2_baseline.csv` (Emax=90, EC50=1.0, Emin=10):
  - Subj01 (C0 ≈ 10): peak ≈ 82–84%, time above 50%: several hours. PASSED
  - Subj02 (C0 ≈ 8): peak ≈ 78–80%, time above 50%: moderate. PASSED
  - Subj03 (C0 ≈ 12): peak ≈ 84–86%, time above 50%: longer. PASSED

- `pd_pmm2_high_ec50.csv` (Emax=90, EC50=5.0): reduced potency — lower activity per subject:
  - Subj01 (C0 ≈ 10): peak ≈ 62–64%, time above 50%: short-to-moderate. PASSED
  - Subj02 (C0 ≈ 8): peak ≈ 58–60%, time above 50%: short. PASSED
  - Subj03 (C0 ≈ 12): peak ≈ 64–66%, time above 50%: moderate. PASSED

- `pd_pmm2_high_emax.csv` (Emax=100, EC50=1.0): higher ceiling — elevated activity per subject:
  - Subj01 (C0 ≈ 10): peak ≈ 91–92%, time above 50%: several hours. PASSED
  - Subj02 (C0 ≈ 8): peak ≈ 87–88%, time above 50%: moderate. PASSED
  - Subj03 (C0 ≈ 12): peak ≈ 93–94%, time above 50%: longest. PASSED

## Report & formatting expectations
- CFU values should be formatted in the report using the same logic in `backend/main.py` (`_format_cfu_value`): large values use comma grouping, very large values use scientific notation.
- PMM2 results are expressed as percentages with reasonable rounding (two decimal places is fine for display).