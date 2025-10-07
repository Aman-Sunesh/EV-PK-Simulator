# pd_models.py
# Pharmacodynamic (PD) models for EV-PK-Simulator backend.
# Includes:
# 1. Bacteria CFU dynamics linked via k_kill(C)
# 2. PMM2 rescue via EV C(t) → %Activity (Hill/Emax)
# 3. Other relevant PD models

import numpy as np

def k_kill_conc(C, k_max, EC50, hill=1.0):
    """
    Concentration-dependent kill rate (Emax/Hill model).
    C: drug concentration (array or float)
    k_max: maximal kill rate
    EC50: concentration for 50% of k_max
    hill: Hill coefficient (default 1)
    Returns: k_kill(C)
    """
    return k_max * (C ** hill) / (EC50 ** hill + C ** hill)

def bacteria_cfu_dynamics(t, CFU0, C_t, k_max, EC50, hill=1.0, k_grow=0.0):
    """
    Simulate bacteria CFU dynamics over time, linked to drug concentration.
    t: time array
    CFU0: initial CFU
    C_t: concentration array (same length as t)
    k_max, EC50, hill: PD params for k_kill(C)
    k_grow: bacterial growth rate (optional)
    Returns: CFU array
    """
    t = np.asarray(t)
    C_t = np.asarray(C_t)

    CFU = np.zeros_like(t, dtype=float)
    CFU[0] = CFU0

    # Loop over time steps to integrate CFU (Euler method)
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        C = C_t[i - 1]
        kill_rate = k_kill_conc(C, k_max, EC50, hill)
        net_rate = k_grow - kill_rate
        CFU[i] = CFU[i - 1] * np.exp(net_rate * dt)

    return CFU

def hill_emax(C, Emax, EC50, hill=1.0, Emin=0.0):
    """
    Hill/Emax model for %Activity (e.g., PMM2 rescue).
    C: drug concentration (array or float)
    Emax: maximal effect (%Activity)
    EC50: concentration for 50% of Emax
    hill: Hill coefficient (default 1)
    Emin: baseline effect (default 0)
    Returns: %Activity (same shape as C)
    """
    return Emin + (Emax - Emin) * (C ** hill) / (EC50 ** hill + C ** hill)

# Example: PMM2 rescue over time
def pmm2_rescue_activity(C_t, Emax, EC50, hill=1.0, Emin=0.0):
    """
    Calculate %Activity over time given C(t).
    C_t: concentration array
    Returns: %Activity array
    """
    return hill_emax(np.array(C_t), Emax, EC50, hill, Emin)
