"""
interface/components/pool_summary.py
-------------------------------------
Seven metric cards summarizing the selected pool.

Metrics displayed:
  - Total Balance (UPB)
  - Loan Count
  - WAC (weighted average coupon)
  - WAM (weighted average maturity)
  - WALA (weighted average loan age)
  - Avg FICO
  - Avg DTI
"""

import streamlit as st
from cashflow.pool import PoolSnapshot


def render(snap: PoolSnapshot, loans_df) -> None:
    """
    Render 7 metric cards for the selected pool.

    Parameters
    ----------
    snap : PoolSnapshot
        Pool-level aggregates from from_lending_club().
    loans_df : pd.DataFrame
        Filtered loans DataFrame (for FICO and DTI, which are not on PoolSnapshot).
    """
    st.subheader("Pool Summary")

    # Compute FICO and DTI weighted averages from the filtered DataFrame
    active = loans_df[loans_df["out_prncp"] > 0]
    weight_col = "out_prncp" if len(active) > 0 else "loan_amnt"
    df_w = active if len(active) > 0 else loans_df

    weights = df_w[weight_col]
    total_w = weights.sum()

    avg_fico = (df_w["fico"] * weights).sum() / total_w if total_w > 0 else float("nan")
    avg_dti  = (df_w["dti"]  * weights).sum() / total_w if total_w > 0 else float("nan")

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

    c1.metric(
        "Balance (UPB)",
        f"${snap.balance / 1e6:.1f}M" if snap.balance >= 1e6 else f"${snap.balance:,.0f}",
    )
    c2.metric("Loans", f"{snap.loan_count:,}")
    c3.metric("WAC", f"{snap.wac:.2%}")
    c4.metric("WAM", f"{snap.wam} mo")
    c5.metric(
        "WALA",
        f"{_compute_wala(loans_df, weight_col):.1f} mo",
    )
    c6.metric("Avg FICO", f"{avg_fico:.0f}")
    c7.metric("Avg DTI", f"{avg_dti:.1f}%")


def _compute_wala(loans_df, weight_col: str) -> float:
    """Weighted average loan age from the filtered DataFrame."""
    import pandas as pd

    ref_date = pd.Timestamp("2018-10-01")
    df = loans_df[loans_df[weight_col] > 0] if weight_col == "out_prncp" else loans_df

    ages = (
        (ref_date.year  - df["issue_date"].dt.year)  * 12 +
        (ref_date.month - df["issue_date"].dt.month)
    ).clip(lower=0)

    weights = df[weight_col]
    total_w = weights.sum()
    return float((ages * weights).sum() / total_w) if total_w > 0 else 0.0
