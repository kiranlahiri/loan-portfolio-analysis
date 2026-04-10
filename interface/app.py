"""
interface/app.py
-----------------
Streamlit application entry point.

Run with:
    streamlit run interface/app.py

Layout
------
  Sidebar  : data source, pool filter, purchase price, scenario sliders, MC settings
  Main     : pool summary → scenario table → cash flow chart (tabbed) → Monte Carlo → history
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path regardless of where streamlit is invoked from
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

# Page config must be the first Streamlit call
st.set_page_config(
    page_title="Aravalli Capital — Loan Portfolio Analysis",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* Monospace font for all metric values and table numbers */
[data-testid="stMetricValue"] {
    font-family: "IBM Plex Mono", "Courier New", monospace;
    font-size: 1.2rem;
    letter-spacing: 0.02em;
}
[data-testid="stMetricLabel"] {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    opacity: 0.6;
}
/* Tighter metric delta */
[data-testid="stMetricDelta"] { font-size: 0.75rem; }

/* Dataframe table — monospace numbers */
.stDataFrame td { font-family: "IBM Plex Mono", monospace; font-size: 0.82rem; }
.stDataFrame th {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    opacity: 0.7;
}

/* Sidebar header */
[data-testid="stSidebar"] .stMarkdown h1 {
    font-size: 1.1rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

/* Divider color */
hr { border-color: rgba(255,255,255,0.1) !important; }

/* Download button — compact */
.stDownloadButton button { font-size: 0.78rem; padding: 0.3rem 0.8rem; }
</style>
""", unsafe_allow_html=True)

from data.ingest import get_loans
from cashflow.pool import PoolSnapshot, from_lending_club
from cashflow.engine import project
from cashflow.scenarios import build_scenarios, compare_scenarios, monte_carlo
from interface.db import init_db
from interface.components import sidebar as sidebar_component
from interface.components import pool_summary, scenarios as scenarios_component
from interface.components import cashflow_chart, monte_carlo as mc_component
from interface.components import history as history_component
from interface.components.export import build_excel


# ---------------------------------------------------------------------------
# Initialise DB
# ---------------------------------------------------------------------------
init_db()


# ---------------------------------------------------------------------------
# Data loading (cached — only re-runs when path changes)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading loan data...")
def load_data(path: str) -> pd.DataFrame:
    return get_loans(path)


@st.cache_data(show_spinner="Loading uploaded file...")
def load_uploaded(file_bytes: bytes) -> pd.DataFrame:
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name
    df = get_loans(tmp_path)
    os.unlink(tmp_path)
    return df


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
inputs = sidebar_component.render()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
if inputs.uploaded_file is not None:
    loans_df = load_uploaded(inputs.uploaded_file.read())
else:
    loans_df = load_data(inputs.data_path)

# ---------------------------------------------------------------------------
# Filter to selected vintage
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Filtering pool...")
def filter_pool(
    _df: pd.DataFrame,
    vintage_year_start: int,
    vintage_year_end: int,
    status_filter: list[str] | None,
) -> pd.DataFrame:
    df = _df.copy()
    df = df[df["issue_date"].dt.year.between(vintage_year_start, vintage_year_end)]
    if status_filter:
        df = df[df["loan_status"].isin(status_filter)]
    return df


filtered_df = filter_pool(
    loans_df,
    inputs.vintage_year_start,
    inputs.vintage_year_end,
    inputs.status_filter,
)

if len(filtered_df) == 0:
    st.error("No loans match the selected filter. Adjust the vintage or status filter.")
    st.stop()

# Warn if selected range includes pre-2012 vintages (different credit regime)
if inputs.vintage_year_start < 2012:
    st.warning(
        "**Regime warning:** Your selected vintage range includes pre-2012 loans. "
        "PSI analysis identified a population break at the 2011→2012 transition — "
        "pre-2012 borrowers represent a different credit regime (post-crisis tightening "
        "had not yet taken effect). "
        "Base CDR/CPR assumptions are calibrated to 2012–2016 completed vintages. "
        "Applying them to earlier vintages may produce unreliable projections."
    )

# ---------------------------------------------------------------------------
# Build PoolSnapshot
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Computing pool metrics...")
def build_snapshot(
    _df: pd.DataFrame,
    vintage_year_start: int,
    vintage_year_end: int,
    status_filter: tuple | None,
    base_cdr: float,
    base_cpr: float,
    base_loss_severity: float,
) -> PoolSnapshot:
    return from_lending_club(
        _df,
        cdr_override=base_cdr,
        cpr_override=base_cpr,
        loss_severity_override=base_loss_severity,
    )


snap = build_snapshot(
    filtered_df,
    inputs.vintage_year_start,
    inputs.vintage_year_end,
    tuple(inputs.status_filter) if inputs.status_filter else None,
    inputs.base_cdr,
    inputs.base_cpr,
    inputs.base_loss_severity,
)

# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------
st.title("Loan Portfolio Analysis")
vintage_label = (
    "Full Pool (2007–2018)"
    if inputs.vintage_year_start == 2007 and inputs.vintage_year_end == 2018
    else f"Vintage {inputs.vintage_year_start}–{inputs.vintage_year_end}"
)
st.caption(
    f"Pool: **{vintage_label}**"
    + f"  |  Purchase Price: **{inputs.purchase_price:.0%}**"
    + f"  |  {len(filtered_df):,} loans"
)

# ---- Pool Summary ----
pool_summary.render(snap, filtered_df)

st.divider()

# ---- Scenario Comparison ----
scenario_list = build_scenarios(
    base_cdr=inputs.base_cdr,
    base_cpr=inputs.base_cpr,
    base_loss_severity=inputs.base_loss_severity,
    stress_cdr=inputs.stress_cdr,
    stress_cpr=inputs.stress_cpr,
    stress_loss_severity=inputs.stress_loss_severity,
    upside_cdr=inputs.upside_cdr,
    upside_cpr=inputs.upside_cpr,
    upside_loss_severity=inputs.upside_loss_severity,
)

with st.spinner("Running scenarios..."):
    scenario_df = compare_scenarios(
        balance=snap.balance,
        wac=snap.wac,
        wam=snap.wam,
        purchase_price=inputs.purchase_price,
        scenarios=scenario_list,
        target_irrs=inputs.target_irrs,
    )

scenarios_component.render(scenario_df, inputs.purchase_price)

st.divider()

# ---- Cash Flow Chart (tabbed by scenario) ----
st.subheader("Cash Flow Projections")

cf_by_scenario = {}
tab_labels = [s["label"] for s in scenario_list]
tabs = st.tabs(tab_labels)

for tab, scenario in zip(tabs, scenario_list):
    with tab:
        with st.spinner(f"Projecting {scenario['label']} cash flows..."):
            cf = project(
                balance=snap.balance,
                wac=snap.wac,
                wam=snap.wam,
                cdr=scenario["cdr"],
                cpr=scenario["cpr"],
                loss_severity=scenario["loss_severity"],
            )
        cf_by_scenario[scenario["label"]] = cf
        cashflow_chart.render(cf, scenario_label=scenario["label"])

st.divider()

# ---- Monte Carlo ----
with st.spinner(f"Running {inputs.n_sims:,} Monte Carlo simulations..."):
    mc = monte_carlo(
        balance=snap.balance,
        wac=snap.wac,
        wam=snap.wam,
        purchase_price=inputs.purchase_price,
        n_sims=inputs.n_sims,
        cdr_mean=inputs.base_cdr,
        cpr_mean=inputs.base_cpr,
        loss_severity=inputs.base_loss_severity,
    )

mc_component.render(mc)

st.divider()

# ---- Export ----
xlsx_bytes = build_excel(scenario_df, cf_by_scenario, mc, inputs.purchase_price)
st.download_button(
    label="Export Analysis (.xlsx)",
    data=xlsx_bytes,
    file_name="aravalli_portfolio_analysis.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=False,
)

st.divider()

# ---- Save / History ----
serializable_inputs = {
    "vintage_year_start": inputs.vintage_year_start,
    "vintage_year_end":   inputs.vintage_year_end,
    "status_filter":      inputs.status_filter,
    "purchase_price":     inputs.purchase_price,
    "base_cdr":           inputs.base_cdr,
    "base_cpr":           inputs.base_cpr,
    "base_loss_severity": inputs.base_loss_severity,
    "stress_cdr":         inputs.stress_cdr,
    "stress_cpr":         inputs.stress_cpr,
    "stress_loss_severity": inputs.stress_loss_severity,
    "upside_cdr":         inputs.upside_cdr,
    "upside_cpr":         inputs.upside_cpr,
    "upside_loss_severity": inputs.upside_loss_severity,
    "n_sims":             inputs.n_sims,
}

serializable_outputs = history_component.outputs_to_serializable(scenario_df, mc)

history_component.render_save_button(serializable_inputs, serializable_outputs)

loaded_run = history_component.render_history()
if loaded_run is not None:
    st.subheader(f"Loaded: {loaded_run['name']}")
    loaded_df, loaded_mc = history_component.outputs_from_stored(loaded_run["outputs"])
    scenarios_component.render(loaded_df, loaded_run["inputs"].get("purchase_price", 0))
    st.caption(f"Saved {loaded_run['created_at'][:19].replace('T', ' ')} UTC")
