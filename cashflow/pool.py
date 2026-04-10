"""
cashflow/pool.py
----------------
PoolSnapshot dataclass and dataset adapters.

PoolSnapshot is the bridge between the data layer and the cash flow engine.
The engine only ever receives a PoolSnapshot — it has no knowledge of
Lending Club, Fannie Mae, or any specific dataset.

Adding support for a new dataset means writing a new from_*() adapter
function that produces a PoolSnapshot. The engine is unchanged.

Adapters implemented:
  - from_lending_club()  : Lending Club 2007-2018Q4 consumer loans
  - from_dict()          : Generic dict for testing or manual input
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class PoolSnapshot:
    """
    Aggregate pool-level inputs required by the cash flow engine.

    All rates are expressed as decimals (e.g. 0.1324 for 13.24%).
    All monetary values are in dollars.

    Attributes
    ----------
    balance : float
        Total outstanding principal balance (UPB).
    wac : float
        Weighted average coupon (decimal).
    wam : int
        Weighted average maturity in months (remaining term).
    cdr : float
        Annual cumulative default rate assumption (decimal).
    cpr : float
        Annual cumulative prepayment rate assumption (decimal).
    loss_severity : float
        Fraction of defaulted balance permanently lost (decimal).
    label : str
        Human-readable label for this pool (e.g. "LC 2016 Vintage").
    loan_count : int
        Number of loans in the pool (informational only).
    """
    balance:       float
    wac:           float
    wam:           int
    cdr:           float
    cpr:           float
    loss_severity: float
    label:         str  = "Pool"
    loan_count:    int  = 0

    def summary(self) -> str:
        return (
            f"{self.label}\n"
            f"  Balance:       ${self.balance:,.0f}\n"
            f"  WAC:           {self.wac:.2%}\n"
            f"  WAM:           {self.wam} months\n"
            f"  CDR:           {self.cdr:.2%}\n"
            f"  CPR:           {self.cpr:.2%}\n"
            f"  Loss Severity: {self.loss_severity:.2%}\n"
            f"  Loans:         {self.loan_count:,}"
        )


# ---------------------------------------------------------------------------
# Historical base assumptions from Part 1 analysis (completed vintages 2012-2016)
# Used as defaults when computing CDR/CPR from incomplete vintages
# ---------------------------------------------------------------------------

_BASE_CDR           = 0.1755   # 17.55% loan-count credibility-weighted CDR, vintages 2012-2016
_BASE_CPR           = 0.4930   # 49.30% avg CPR, completed vintages 2012-2016
_BASE_LOSS_SEVERITY = 0.9176   # 91.76% loss severity, completed vintages 2012-2016

# Reference date for age calculations (dataset cutoff)
_REFERENCE_DATE = pd.Timestamp("2018-10-01")


def from_lending_club(
    loans: pd.DataFrame,
    vintage_year: Optional[int] = None,
    vintage_quarter: Optional[str] = None,
    status_filter: Optional[list] = None,
    cdr_override: Optional[float] = None,
    cpr_override: Optional[float] = None,
    loss_severity_override: Optional[float] = None,
) -> PoolSnapshot:
    """
    Build a PoolSnapshot from a clean Lending Club loans DataFrame.

    Parameters
    ----------
    loans : pd.DataFrame
        Output of data.ingest.load_clean_loans(). Must contain columns:
        loan_amnt, out_prncp, int_rate, term_months, issue_date,
        loan_status, last_pymnt_date, recoveries.
    vintage_year : int or None
        Filter to a specific origination year (e.g. 2016).
    vintage_quarter : str or None
        Filter to a specific quarter (e.g. "2016Q1"). Format: "YYYYQn".
        Overrides vintage_year if both are provided.
    status_filter : list or None
        Filter to specific loan statuses. Default: all statuses.
        Common use: ['Current'] for active-only pool.
    cdr_override : float or None
        Override CDR assumption. If None, computed from observed data
        (or base assumption for incomplete vintages).
    cpr_override : float or None
        Override CPR assumption. If None, computed from observed data.
    loss_severity_override : float or None
        Override loss severity. If None, computed from observed data.

    Returns
    -------
    PoolSnapshot
    """
    df = loans.copy()

    # --- Apply filters ---
    if vintage_quarter is not None:
        year = int(vintage_quarter[:4])
        q    = int(vintage_quarter[5])
        df = df[
            (df["issue_date"].dt.year == year) &
            (df["issue_date"].dt.quarter == q)
        ]
        label = f"LC {vintage_quarter}"
    elif vintage_year is not None:
        df = df[df["issue_date"].dt.year == vintage_year]
        label = f"LC {vintage_year} Vintage"
    else:
        label = "LC Full Pool"

    if status_filter is not None:
        df = df[df["loan_status"].isin(status_filter)]

    if len(df) == 0:
        raise ValueError("No loans match the specified filters.")

    # --- Active sub-pool for WAC/WAM/WALA (loans with outstanding balance) ---
    active = df[df["out_prncp"] > 0]
    if len(active) == 0:
        # Vintage fully resolved — use loan_amnt as proxy weight
        active = df
        weight_col = "loan_amnt"
    else:
        weight_col = "out_prncp"

    total_balance = active[weight_col].sum()

    # WAC — weighted average coupon
    wac = (active["int_rate"] * active[weight_col]).sum() / total_balance / 100.0

    # WALA — weighted average loan age
    active = active.copy()
    active["loan_age"] = (
        (_REFERENCE_DATE.year - active["issue_date"].dt.year) * 12 +
        (_REFERENCE_DATE.month - active["issue_date"].dt.month)
    ).clip(lower=0)
    wala = (active["loan_age"] * active[weight_col]).sum() / total_balance

    # WAM — weighted average maturity
    active["remaining"] = (active["term_months"] - active["loan_age"]).clip(lower=0)
    wam = int(round(
        (active["remaining"] * active[weight_col]).sum() / total_balance
    ))
    wam = max(wam, 1)

    # Balance = total outstanding principal
    balance = total_balance

    # --- CDR ---
    if cdr_override is not None:
        cdr = cdr_override
    else:
        defaulted = df[df["loan_status"].isin(["Charged Off", "Default"])]["loan_amnt"].sum()
        total_orig = df["loan_amnt"].sum()
        observed_cdr = defaulted / total_orig if total_orig > 0 else 0

        # Check if vintage is complete (>95% resolved)
        resolved = df[df["loan_status"].isin(
            ["Fully Paid", "Charged Off", "Default"]
        )]["loan_amnt"].sum()
        pct_resolved = resolved / total_orig if total_orig > 0 else 0

        if pct_resolved >= 0.95:
            cdr = observed_cdr
        else:
            # Incomplete vintage — use base assumption with a note
            # A more rigorous approach would apply the Delta method here
            cdr = _BASE_CDR

    # --- CPR ---
    if cpr_override is not None:
        cpr = cpr_override
    else:
        fully_paid = df[df["loan_status"] == "Fully Paid"]
        if len(fully_paid) > 0 and "last_pymnt_date" in df.columns:
            fp = fully_paid.copy()
            fp["scheduled_maturity"] = (
                fp["issue_date"].dt.to_period("M") + (fp["term_months"] - 1)
            ).dt.to_timestamp()
            prepaid = fp[fp["last_pymnt_date"] < fp["scheduled_maturity"]]
            observed_cpr = prepaid["loan_amnt"].sum() / df["loan_amnt"].sum()
        else:
            observed_cpr = 0

        total_orig = df["loan_amnt"].sum()
        resolved = df[df["loan_status"].isin(
            ["Fully Paid", "Charged Off", "Default"]
        )]["loan_amnt"].sum()
        pct_resolved = resolved / total_orig if total_orig > 0 else 0

        if pct_resolved >= 0.95:
            cpr = observed_cpr
        else:
            cpr = _BASE_CPR

    # --- Loss severity ---
    if loss_severity_override is not None:
        loss_severity = loss_severity_override
    else:
        defaulted_df = df[df["loan_status"].isin(["Charged Off", "Default"])]
        if len(defaulted_df) > 0:
            total_defaulted = defaulted_df["loan_amnt"].sum()
            total_recovered = defaulted_df["recoveries"].sum()
            loss_severity = (total_defaulted - total_recovered) / total_defaulted
        else:
            loss_severity = _BASE_LOSS_SEVERITY

    return PoolSnapshot(
        balance=float(balance),
        wac=float(wac),
        wam=int(wam),
        cdr=float(cdr),
        cpr=float(cpr),
        loss_severity=float(loss_severity),
        label=label,
        loan_count=len(df),
    )


def from_dict(d: dict) -> PoolSnapshot:
    """
    Build a PoolSnapshot from a plain dictionary.

    Useful for testing and manual scenario construction.

    Example
    -------
    >>> snap = from_dict({
    ...     "balance": 1_000_000,
    ...     "wac": 0.1324,
    ...     "wam": 39,
    ...     "cdr": 0.17,
    ...     "cpr": 0.49,
    ...     "loss_severity": 0.9176,
    ... })
    """
    required = ["balance", "wac", "wam", "cdr", "cpr", "loss_severity"]
    missing = [k for k in required if k not in d]
    if missing:
        raise ValueError(f"Missing required keys: {missing}")

    return PoolSnapshot(
        balance=float(d["balance"]),
        wac=float(d["wac"]),
        wam=int(d["wam"]),
        cdr=float(d["cdr"]),
        cpr=float(d["cpr"]),
        loss_severity=float(d["loss_severity"]),
        label=d.get("label", "Pool"),
        loan_count=int(d.get("loan_count", 0)),
    )
