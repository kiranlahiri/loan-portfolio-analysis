"""
cashflow/scenarios.py
---------------------
Scenario definitions, comparison runner, and Monte Carlo simulation.

Base assumptions are derived from Part 1 historical analysis:
  CDR          : 17.55%  (loan-count credibility-weighted, vintages 2012-2016)
  CPR          : 49.30%  (avg completed vintages 2012-2016)
  Loss severity: 91.76%  (avg completed vintages 2012-2016)

Stress / upside multipliers are documented industry conventions, applied
consistently across all three parameters (CDR, CPR, loss severity):

  Stress (recession):
    2× CDR, 0.5× CPR, loss severity unchanged.
    Convention rationale: in a credit downturn, defaults spike while
    prepayments fall (tighter credit standards prevent refinancing).
    Loss severity is structurally driven by the unsecured nature of the
    loans and does not vary materially with the credit cycle (91-92%
    observed across all 2012-2016 vintages).

    Empirical calibration was attempted using 2007-2009 LC recession
    vintages (n=6,529 loans) but was not feasible: the sample is too small
    for statistical significance, and early LC approved only its highest-
    quality borrowers (selection bias), making those vintages unrepresentative
    of a true stress environment. Multipliers are therefore documented
    conventions, consistent with standard credit analysis practice.

  Upside (recovery/goldilocks):
    0.5× CDR, 1.5× CPR, loss severity unchanged.
    Convention rationale: benign credit environment — low unemployment,
    strong income growth, available credit. Borrowers refinance freely
    (high CPR) and default rates fall. Symmetric to the stress assumption
    to bracket the base case evenly.

All three scenario parameters use the same methodology (convention) so
that the scenarios are internally consistent. The analyst can override
any parameter independently via build_scenarios() or compare_scenarios().

Monte Carlo draws CDR and CPR from normal distributions calibrated to
the spread observed across completed vintages, allowing the analyst to
see the full IRR distribution rather than three point estimates.
"""

import numpy as np
import pandas as pd

from cashflow.irr import compute_irr, solve_price


# ---------------------------------------------------------------------------
# Base assumptions from Part 1 analysis
# ---------------------------------------------------------------------------

BASE_CDR           = 0.1755   # 17.55% loan-count credibility-weighted CDR, vintages 2012-2016
BASE_CPR           = 0.4930   # 49.30% avg CPR, completed vintages 2012-2016
BASE_LOSS_SEVERITY = 0.9176   # 91.76% loss severity, completed vintages 2012-2016

# Vintage selection: 2012-2016, validated by PSI analysis (see notebook).
# DTI PSI = 0.41 between 2011->2012 identifies a population break — LC changed underwriting.
# All consecutive PSI values within 2012-2016 are < 0.10 (stable regime).
# Excludes 2017-2018: incomplete performance (loans still outstanding).
# Note: BASE_CDR is a point-in-time (PIT) benign-cycle estimate, NOT through-the-cycle (TTC).
# The stress scenario (2x CDR) partially compensates for this.

# CDR spread across 2012-2016 vintages: [17.7%, 16.6%, 18.3%, 18.6%, 16.4%]
# Loan-count weighted std = 0.0098 (data-derived, replaces eyeballed 0.009)
CDR_STD = 0.0098
CPR_STD = 0.047

# CDR/CPR correlation for Monte Carlo.
# Empirical correlation across 2012-2016 vintages is +0.25, but this is a
# statistical artifact: 2016 loans are not fully resolved at the data cutoff
# (2018Q4), so both CDR and CPR are understated for that vintage, creating
# spurious co-movement. With only 5 data points the estimate is also unreliable.
#
# Economic reasoning: in a credit downturn, defaults rise while prepayments
# fall (tighter underwriting prevents refinancing). This implies a negative
# relationship. A correlation of -0.4 is used as a documented convention —
# moderate negative, directionally correct, consistent with standard ABS
# stress analysis practice.
CDR_CPR_CORRELATION = -0.4


# ---------------------------------------------------------------------------
# Scenario parameter dictionaries
# ---------------------------------------------------------------------------

SCENARIOS = {
    "base": {
        "cdr": BASE_CDR,
        "cpr": BASE_CPR,
        "loss_severity": BASE_LOSS_SEVERITY,
        "label": "Base",
        "description": "Historical observed (avg 2012-2016 completed vintages)",
    },
    "stress": {
        "cdr": BASE_CDR * 2.0,
        "cpr": BASE_CPR * 0.5,
        "loss_severity": BASE_LOSS_SEVERITY,  # unchanged — unsecured severity is structural, not cyclical
        "label": "Stress",
        "description": "Recession: 2× CDR, 0.5× CPR (documented convention — see module docstring)",
    },
    "upside": {
        "cdr": BASE_CDR * 0.5,
        "cpr": BASE_CPR * 1.5,
        "loss_severity": BASE_LOSS_SEVERITY,  # unchanged — symmetric assumption
        "label": "Upside",
        "description": "Recovery: 0.5× CDR, 1.5× CPR (documented convention — see module docstring)",
    },
}


# ---------------------------------------------------------------------------
# Scenario builder
# ---------------------------------------------------------------------------

def build_scenarios(
    base_cdr: float = BASE_CDR,
    base_cpr: float = BASE_CPR,
    base_loss_severity: float = BASE_LOSS_SEVERITY,
    stress_cdr: float | None = None,
    stress_cpr: float | None = None,
    stress_loss_severity: float | None = None,
    upside_cdr: float | None = None,
    upside_cpr: float | None = None,
    upside_loss_severity: float | None = None,
) -> list[dict]:
    """
    Build a list of scenario parameter dicts for compare_scenarios().

    Defaults reproduce the standard base/stress/upside conventions:
      Stress : 2× CDR, 0.5× CPR  (recession: defaults spike, prepayments fall)
      Upside : 0.5× CDR, 1.5× CPR (recovery: defaults fall, refinancing rises)

    All parameters can be overridden independently, allowing the analyst
    to test any combination of CDR, CPR, and loss severity assumptions.

    Parameters
    ----------
    base_cdr : float
        Base scenario CDR (default: 17.55%, avg completed vintages 2012-2016).
    base_cpr : float
        Base scenario CPR (default: 49.30%, avg completed vintages 2012-2016).
    base_loss_severity : float
        Base scenario loss severity (default: 91.76%, avg 2012-2016).
    stress_cdr : float or None
        Stress CDR override. Default: 2× base_cdr (recession assumption).
    stress_cpr : float or None
        Stress CPR override. Default: 0.5× base_cpr (fewer prepayments in recession).
    stress_loss_severity : float or None
        Stress loss severity override. Default: same as base.
    upside_cdr : float or None
        Upside CDR override. Default: 0.5× base_cdr (recovery assumption).
    upside_cpr : float or None
        Upside CPR override. Default: 1.5× base_cpr (more refinancing in recovery).
    upside_loss_severity : float or None
        Upside loss severity override. Default: same as base.

    Returns
    -------
    list[dict]
        List of scenario dicts, each with keys:
        cdr, cpr, loss_severity, label, description.
    """
    return [
        {
            "cdr":           base_cdr,
            "cpr":           base_cpr,
            "loss_severity": base_loss_severity,
            "label":         "Base",
            "description":   f"Historical observed (avg 2012-2016 completed vintages): CDR={base_cdr:.2%}, CPR={base_cpr:.2%}",
        },
        {
            "cdr":           stress_cdr           if stress_cdr           is not None else base_cdr * 2.0,
            "cpr":           stress_cpr           if stress_cpr           is not None else base_cpr * 0.5,
            "loss_severity": stress_loss_severity if stress_loss_severity is not None else base_loss_severity,
            "label":         "Stress",
            "description":   "Recession: 2× CDR, 0.5× CPR (convention)" if stress_cdr is None else "Stress (custom)",
        },
        {
            "cdr":           upside_cdr           if upside_cdr           is not None else base_cdr * 0.5,
            "cpr":           upside_cpr           if upside_cpr           is not None else base_cpr * 1.5,
            "loss_severity": upside_loss_severity if upside_loss_severity is not None else base_loss_severity,
            "label":         "Upside",
            "description":   "Recovery: 0.5× CDR, 1.5× CPR (convention)" if upside_cdr is None else "Upside (custom)",
        },
    ]


# ---------------------------------------------------------------------------
# Scenario comparison
# ---------------------------------------------------------------------------

def compare_scenarios(
    balance: float,
    wac: float,
    wam: int,
    purchase_price: float,
    scenarios: list[dict] | None = None,
    target_irrs: tuple = (0.10, 0.12, 0.15),
    timing_curve: np.ndarray | None = None,
) -> pd.DataFrame:
    """
    Run scenarios and return an IRR comparison table.

    By default runs base / stress / upside using historical assumptions
    (avg completed vintages 2012-2016):
      Stress : 2× CDR, 0.5× CPR  (recession: defaults spike, prepayments fall)
      Upside : 0.5× CDR, 1.5× CPR (recovery: defaults fall, refinancing rises)

    To run custom scenarios, pass a list of dicts via the `scenarios` parameter.
    Use build_scenarios() to construct the list with overrides, or pass arbitrary
    dicts directly (each must have keys: cdr, cpr, loss_severity, label, description).

    Parameters
    ----------
    balance : float
        Total outstanding principal (UPB).
    wac : float
        Weighted average coupon as a decimal.
    wam : int
        Weighted average maturity in months.
    purchase_price : float
        Price paid as a fraction of UPB (e.g. 0.85).
    scenarios : list[dict] or None
        List of scenario parameter dicts. If None, uses build_scenarios()
        defaults (base/stress/upside from historical 2012-2016 assumptions).
        Each dict must have: cdr, cpr, loss_severity, label, description.
    target_irrs : tuple
        IRR targets for price solving (default: 10%, 12%, 15%).
    timing_curve : np.ndarray or None
        Optional default timing curve (see engine.project).

    Returns
    -------
    pd.DataFrame
        One row per scenario with columns:
        scenario, description, cdr, cpr, loss_severity, irr,
        and one price_for_Xpct_irr column per target in target_irrs.
    """
    if scenarios is None:
        scenarios = build_scenarios()

    rows = []
    for params in scenarios:
        irr = compute_irr(
            balance, wac, wam,
            params["cdr"], params["cpr"], params["loss_severity"],
            purchase_price, timing_curve,
        )

        # Solve for prices at each target IRR
        target_prices = {}
        for target in target_irrs:
            try:
                price = solve_price(
                    balance, wac, wam,
                    params["cdr"], params["cpr"], params["loss_severity"],
                    target_irr=target,
                    timing_curve=timing_curve,
                )
                target_prices[target] = round(price, 4)
            except ValueError:
                target_prices[target] = np.nan

        row = {
            "scenario":      params["label"],
            "description":   params["description"],
            "cdr":           params["cdr"],
            "cpr":           params["cpr"],
            "loss_severity": params["loss_severity"],
            "irr":           irr,
        }
        for target in target_irrs:
            col = f"price_for_{int(target * 100)}pct_irr"
            row[col] = target_prices[target]

        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Monte Carlo simulation
# ---------------------------------------------------------------------------

def monte_carlo(
    balance: float,
    wac: float,
    wam: int,
    purchase_price: float,
    n_sims: int = 10_000,
    cdr_mean: float = BASE_CDR,
    cpr_mean: float = BASE_CPR,
    loss_severity: float = BASE_LOSS_SEVERITY,
    timing_curve: np.ndarray | None = None,
    seed: int | None = 42,
) -> dict:
    """
    Monte Carlo simulation of IRR distribution.

    Draws CDR and CPR from a bivariate normal distribution with a fixed
    negative correlation (-0.4), reflecting the economic relationship between
    default rates and prepayment rates in a credit downturn.

    Uncertainty parameters are fixed to the 2012-2016 completed vintage
    calibration and do not vary with the user's pool selection:
      CDR_STD = 0.0098  (vintage-to-vintage spread, 2012-2016)
      CPR_STD = 0.047   (vintage-to-vintage spread, 2012-2016)
      Correlation = -0.4 (economic convention — see CDR_CPR_CORRELATION)

    This means the simulation answers: "Given your base CDR/CPR assumptions,
    what is the IRR distribution if performance varies the way completed
    2012-2016 vintages varied around their means?" It represents benign-cycle
    vintage-to-vintage variation, not full economic cycle uncertainty.

    Loss severity is not simulated — empirically stable at 91-92% across
    all 2012-2016 vintages (structurally driven by unsecured loan nature).

    Parameters
    ----------
    balance : float
        Total outstanding principal (UPB).
    wac : float
        Weighted average coupon as a decimal.
    wam : int
        Weighted average maturity in months.
    purchase_price : float
        Price paid as a fraction of UPB.
    n_sims : int
        Number of simulations (default 10,000).
    cdr_mean : float
        Mean of CDR distribution — user's base CDR assumption.
    cpr_mean : float
        Mean of CPR distribution — user's base CPR assumption.
    loss_severity : float
        Fixed loss severity (not simulated).
    timing_curve : np.ndarray or None
        Optional default timing curve (see engine.project).
    seed : int or None
        Random seed for reproducibility (default 42).

    Returns
    -------
    dict with keys:
        irrs          : np.ndarray of simulated IRRs (length n_sims)
        mean          : float, mean IRR
        median        : float, median IRR
        std           : float, standard deviation of IRR
        p5            : float, 5th percentile IRR
        p1            : float, 1st percentile IRR
        prob_loss     : float, probability of negative IRR
        cdr_draws     : np.ndarray of CDR draws used
        cpr_draws     : np.ndarray of CPR draws used
    """
    rng = np.random.default_rng(seed)

    # Bivariate normal draw with fixed negative correlation
    cov = CDR_CPR_CORRELATION * CDR_STD * CPR_STD
    cov_matrix = [
        [CDR_STD ** 2, cov],
        [cov,          CPR_STD ** 2],
    ]
    draws = rng.multivariate_normal([cdr_mean, cpr_mean], cov_matrix, n_sims)
    cdr_draws = draws[:, 0].clip(0.001, 0.999)
    cpr_draws = draws[:, 1].clip(0.001, 0.999)

    irrs = np.array([
        compute_irr(
            balance, wac, wam,
            cdr, cpr, loss_severity,
            purchase_price, timing_curve,
        )
        for cdr, cpr in zip(cdr_draws, cpr_draws)
    ])

    # Filter out any nan results (edge cases where IRR can't be computed)
    valid = irrs[~np.isnan(irrs)]

    return {
        "irrs":      irrs,
        "mean":      float(np.mean(valid)),
        "median":    float(np.median(valid)),
        "std":       float(np.std(valid)),
        "p5":        float(np.percentile(valid, 5)),
        "p1":        float(np.percentile(valid, 1)),
        "prob_loss": float(np.mean(valid < 0)),
        "cdr_draws": cdr_draws,
        "cpr_draws": cpr_draws,
    }
