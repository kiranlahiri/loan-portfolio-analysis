"""
interface/components/scenarios.py
-----------------------------------
Scenario comparison table with color coding via pandas Styler.
"""

import pandas as pd
import streamlit as st


_SCENARIO_ROW_COLORS = {
    "Base":   "background-color: #1a2a4a; color: #e6edf3;",
    "Stress": "background-color: #3a1a1a; color: #e6edf3;",
    "Upside": "background-color: #1a3a2a; color: #e6edf3;",
}

_SCENARIO_LABEL_COLORS = {
    "Base":   "color: #4d94ff; font-weight: bold;",
    "Stress": "color: #ff4757; font-weight: bold;",
    "Upside": "color: #2ed573; font-weight: bold;",
}


def render(scenario_df: pd.DataFrame, purchase_price: float) -> None:
    st.subheader("Scenario Comparison")
    st.caption(
        f"Purchase price: **{purchase_price:.0%}** of UPB. "
        "IRR annualized as nominal APR (consistent with Lending Club int_rate convention)."
    )

    # Build display DataFrame
    price_cols = [c for c in scenario_df.columns if c.startswith("price_for_")]
    display = scenario_df[["scenario", "cdr", "cpr", "loss_severity", "irr"] + price_cols].copy()

    # Rename columns
    rename = {
        "scenario":      "Scenario",
        "cdr":           "CDR",
        "cpr":           "CPR",
        "loss_severity": "Loss Sev.",
        "irr":           "IRR",
    }
    for col in price_cols:
        pct = col.replace("price_for_", "").replace("pct_irr", "")
        rename[col] = f"Price @ {pct}% IRR"
    display = display.rename(columns=rename)

    # Format values
    for col in ["CDR", "CPR", "Loss Sev.", "IRR"]:
        display[col] = display[col].apply(
            lambda v: f"{float(v):.2%}" if pd.notna(v) else "N/A"
        )
    for col in [c for c in display.columns if c.startswith("Price @")]:
        display[col] = display[col].apply(
            lambda v: f"{float(v):.4f}" if pd.notna(v) else "N/A"
        )

    # Apply styling
    scenarios = display["Scenario"].tolist()

    def style_rows(row):
        label = row["Scenario"]
        base = _SCENARIO_ROW_COLORS.get(label, "background-color: #1c2333; color: #e6edf3;")
        return [base] * len(row)

    def style_scenario_col(val):
        return _SCENARIO_LABEL_COLORS.get(val, "color: #e6edf3;")

    def style_irr(val):
        if val == "N/A":
            return "color: #e6edf3;"
        try:
            v = float(val.strip("%")) / 100
            if v >= 0.12:
                return "color: #2ed573; font-weight: bold;"
            elif v >= 0.08:
                return "color: #ffeaa7; font-weight: bold;"
            else:
                return "color: #ff4757; font-weight: bold;"
        except Exception:
            return "color: #e6edf3;"

    styler = (
        display.style
        .apply(style_rows, axis=1)
        .map(style_scenario_col, subset=["Scenario"])
        .map(style_irr, subset=["IRR"])
        .set_properties(**{
            "font-family": "'IBM Plex Mono', monospace",
            "font-size": "0.83rem",
            "text-align": "right",
        })
        .set_properties(subset=["Scenario"], **{"text-align": "left"})
        .hide(axis="index")
    )

    st.dataframe(styler, width="stretch", hide_index=True)

    st.write("")


def _fmt_irr(v) -> str:
    if pd.isna(v):
        return "N/A"
    return f"{float(v):.2%}"
