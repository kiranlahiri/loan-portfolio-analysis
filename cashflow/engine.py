"""
cashflow/engine.py
------------------
Pool-level monthly cash flow projection engine.

This module is the mathematical core of the system. It has no dependencies
on pandas, the data layer, or the interface layer — it operates purely on
scalar inputs and returns numpy arrays.

Design follows Moody's Consumer Loan ABS Methodology (July 2024):
  - §3:   CDR as primary default metric
  - §6.3: Front-loaded default timing (peaks months 12-24)
  - §6.4: Loss severity for unsecured consumer loans

Waterfall order each month (standard ABS convention):
  1. Apply defaults to beginning balance
  2. Apply prepayments to post-default balance
  3. Remaining balance makes scheduled amortization payment
  4. Losses = defaults × loss_severity
"""

import numpy as np


def _monthly_rate(annual_rate: float) -> float:
    """
    Convert an annual CDR/CPR rate to its monthly equivalent (SMM).

    Uses the standard ABS/MBS convention:
        SMM = 1 - (1 - annual_rate)^(1/12)

    This differs from compound interest annualization. At CDR/CPR = 100%,
    SMM = 1.0 (entire pool defaults/prepays in a single month), which is
    the correct limiting behavior.

    Note: WAC (interest rate) is applied as wac/12 (nominal APR convention),
    consistent with how Lending Club reports int_rate. These are two different
    conventions for two different types of rates — do not mix them.
    """
    return 1 - (1 - annual_rate) ** (1 / 12)


def _scheduled_payment(balance: float, monthly_rate: float, periods: int) -> float:
    """
    Standard level-payment annuity formula.

    P = B × r / (1 - (1 + r)^-n)

    Returns 0 if balance or periods is 0.
    """
    if balance <= 0 or periods <= 0:
        return 0.0
    if monthly_rate == 0:
        return balance / periods
    return balance * monthly_rate / (1 - (1 + monthly_rate) ** (-periods))


def project(
    balance: float,
    wac: float,
    wam: int,
    cdr: float,
    cpr: float,
    loss_severity: float,
    timing_curve: np.ndarray | None = None,
) -> dict:
    """
    Project monthly cash flows for a loan pool.

    Parameters
    ----------
    balance : float
        Total outstanding principal balance (UPB) at start of projection.
    wac : float
        Weighted average coupon as a decimal (e.g. 0.1324 for 13.24%).
    wam : int
        Weighted average maturity in months (remaining term).
    cdr : float
        Annual cumulative default rate assumption as a decimal (e.g. 0.17).
    cpr : float
        Annual cumulative prepayment rate assumption as a decimal (e.g. 0.49).
    loss_severity : float
        Fraction of defaulted balance that is permanently lost (e.g. 0.9176).
    timing_curve : np.ndarray or None
        Optional array of length wam. Each element is the fraction of total
        lifetime defaults that occur in that month. Must sum to 1.0.
        If None, defaults are applied uniformly via constant MDR each month.
        Per Moody's §6.3, defaults are front-loaded (73% by month 24).

    Returns
    -------
    dict with keys:
        interest    : np.ndarray, monthly interest cash flows
        principal   : np.ndarray, monthly scheduled principal cash flows
        prepayments : np.ndarray, monthly prepayment cash flows (principal)
        defaults    : np.ndarray, monthly defaulted balance
        losses      : np.ndarray, monthly net losses (defaults × severity)
        net_cf      : np.ndarray, monthly net cash flows to investor
                      (interest + principal + prepayments - losses)
        balance_sod : np.ndarray, pool balance at start of each month
    """
    wam = int(wam)
    n = wam

    # Convert annual rates to monthly compound equivalents
    # Using compound formula, not simple division — MDR/12 overstates defaults
    mdr = _monthly_rate(cdr)   # monthly default rate
    mpr = _monthly_rate(cpr)   # monthly prepayment rate
    mr  = wac / 12             # monthly interest rate (WAC already monthly-equivalent)

    # Validate timing curve if provided
    if timing_curve is not None:
        timing_curve = np.asarray(timing_curve, dtype=float)
        if len(timing_curve) != n:
            raise ValueError(
                f"timing_curve length {len(timing_curve)} != wam {n}"
            )
        if not np.isclose(timing_curve.sum(), 1.0, atol=1e-4):
            raise ValueError(
                f"timing_curve must sum to 1.0, got {timing_curve.sum():.6f}"
            )

    # Pre-allocate output arrays
    interest_cf    = np.zeros(n)
    principal_cf   = np.zeros(n)
    prepayment_cf  = np.zeros(n)
    defaults_cf    = np.zeros(n)
    losses_cf      = np.zeros(n)
    balance_sod    = np.zeros(n)

    current_balance = float(balance)

    for t in range(n):
        if current_balance <= 0:
            break

        balance_sod[t] = current_balance

        # --- Step 1: Defaults ---
        if timing_curve is not None:
            # Scale total CDR by timing curve increment for this month
            # timing_curve[t] is the marginal fraction defaulting this month
            month_default = current_balance * timing_curve[t] * cdr
        else:
            month_default = current_balance * mdr

        month_default = min(month_default, current_balance)
        current_balance -= month_default

        # --- Step 2: Prepayments ---
        month_prepay = current_balance * mpr
        month_prepay = min(month_prepay, current_balance)
        current_balance -= month_prepay

        # --- Step 3: Scheduled amortization on remaining balance ---
        remaining_periods = n - t
        payment = _scheduled_payment(current_balance, mr, remaining_periods)
        month_interest   = current_balance * mr
        month_principal  = min(payment - month_interest, current_balance)
        month_principal  = max(month_principal, 0.0)
        current_balance -= month_principal

        # --- Step 4: Losses ---
        month_loss = month_default * loss_severity

        # Store results
        interest_cf[t]   = month_interest
        principal_cf[t]  = month_principal
        prepayment_cf[t] = month_prepay
        defaults_cf[t]   = month_default
        losses_cf[t]     = month_loss

    net_cf = interest_cf + principal_cf + prepayment_cf - losses_cf

    return {
        "interest":    interest_cf,
        "principal":   principal_cf,
        "prepayments": prepayment_cf,
        "defaults":    defaults_cf,
        "losses":      losses_cf,
        "net_cf":      net_cf,
        "balance_sod": balance_sod,
    }
