"""
interface/components/sidebar.py
--------------------------------
Sidebar inputs: data source, vintage filter, purchase price, and
full scenario controls (CDR / CPR / loss severity for each scenario).

Returns a single SidebarInputs dataclass so app.py has a typed,
named bundle of everything the engine needs.

The data source section (file uploader) sits outside the form because
Streamlit does not allow file_uploader inside st.form. All other inputs
are wrapped in a form so nothing triggers a rerun until the user clicks
"Run Analysis".
"""

from dataclasses import dataclass
import streamlit as st

from cashflow.scenarios import BASE_CDR, BASE_CPR, BASE_LOSS_SEVERITY

DEFAULT_PATH = "accepted_2007_to_2018Q4.parquet"


@dataclass
class SidebarInputs:
    # Pool filter
    vintage_year_start: int          # first year of vintage range (inclusive)
    vintage_year_end:   int          # last year of vintage range (inclusive)
    status_filter:      list[str] | None

    # Purchase price
    purchase_price: float

    # Scenario parameters
    base_cdr:           float
    base_cpr:           float
    base_loss_severity: float

    stress_cdr:           float
    stress_cpr:           float
    stress_loss_severity: float

    upside_cdr:           float
    upside_cpr:           float
    upside_loss_severity: float

    # Monte Carlo
    n_sims: int

    # Target IRRs for price solving
    target_irrs: tuple[float, ...]


def render() -> SidebarInputs:
    """Render the sidebar and return all user inputs as a SidebarInputs instance."""

    st.sidebar.title("Aravalli Capital")
    st.sidebar.caption("Loan Portfolio Analysis Tool")
    st.sidebar.divider()

    # -------------------------------------------------------------------------
    uploaded_file = None
    data_path = DEFAULT_PATH

    st.sidebar.divider()

    # -------------------------------------------------------------------------
    # Pool filter — outside the form so vintage range updates immediately
    # -------------------------------------------------------------------------
    st.sidebar.subheader("Pool Filter")

    vintage_year_start, vintage_year_end = st.sidebar.select_slider(
        "Vintage Range",
        options=list(range(2007, 2019)),
        value=(2007, 2018),
        help="Select the origination year range to analyze. Drag both ends to define the cohort.",
    )

    status_options = [
        "Current", "Fully Paid", "Charged Off", "Default",
        "Late (31-120 days)", "Late (16-30 days)", "In Grace Period",
    ]
    selected_statuses = st.sidebar.multiselect(
        "Loan Status Filter",
        status_options,
        default=[],
        help="Leave empty to include all statuses.",
    )
    status_filter = selected_statuses if selected_statuses else None

    st.sidebar.divider()

    # -------------------------------------------------------------------------
    # Form — batches price / scenario / MC inputs; nothing fires until "Run Analysis"
    # -------------------------------------------------------------------------
    with st.sidebar.form("analysis_form"):

        # --- Purchase price ---
        st.subheader("Purchase Price")

        purchase_price = st.slider(
            "Price (cents on the dollar)",
            min_value=50,
            max_value=110,
            value=85,
            step=1,
            format="%d¢",
            help="Price paid as a percentage of outstanding principal balance (UPB).",
        ) / 100.0

        st.divider()

        # --- Scenario parameters ---
        st.subheader("Scenarios")
        st.caption(
            "Defaults: historical avg 2012-2016 completed vintages. "
            "Stress = 2× CDR, 0.5× CPR. Upside = 0.5× CDR, 1.5× CPR."
        )

        with st.expander("Base scenario", expanded=False):
            base_cdr = st.slider(
                "CDR", 0.0, 50.0, round(float(BASE_CDR) * 100, 1), 0.1,
                format="%.1f%%", key="base_cdr",
                help="Annual cumulative default rate.",
            ) / 100.0
            base_cpr = st.slider(
                "CPR", 0.0, 100.0, round(float(BASE_CPR) * 100, 1), 0.1,
                format="%.1f%%", key="base_cpr",
                help="Annual cumulative prepayment rate.",
            ) / 100.0
            base_loss_severity = st.slider(
                "Loss Severity", 0.0, 100.0, round(float(BASE_LOSS_SEVERITY) * 100, 1), 0.1,
                format="%.1f%%", key="base_sev",
                help="Fraction of defaulted balance permanently lost.",
            ) / 100.0

        with st.expander("Stress scenario", expanded=False):
            stress_cdr = st.slider(
                "CDR", 0.0, 80.0, round(float(BASE_CDR) * 2.0 * 100, 1), 0.1,
                format="%.1f%%", key="stress_cdr",
            ) / 100.0
            stress_cpr = st.slider(
                "CPR", 0.0, 100.0, round(float(BASE_CPR) * 0.5 * 100, 1), 0.1,
                format="%.1f%%", key="stress_cpr",
            ) / 100.0
            stress_loss_severity = st.slider(
                "Loss Severity", 0.0, 100.0, round(float(BASE_LOSS_SEVERITY) * 100, 1), 0.1,
                format="%.1f%%", key="stress_sev",
            ) / 100.0

        with st.expander("Upside scenario", expanded=False):
            upside_cdr = st.slider(
                "CDR", 0.0, 50.0, round(float(BASE_CDR) * 0.5 * 100, 1), 0.1,
                format="%.1f%%", key="upside_cdr",
            ) / 100.0
            upside_cpr = st.slider(
                "CPR", 0.0, 100.0, min(round(float(BASE_CPR) * 1.5 * 100, 1), 100.0), 0.1,
                format="%.1f%%", key="upside_cpr",
            ) / 100.0
            upside_loss_severity = st.slider(
                "Loss Severity", 0.0, 100.0, round(float(BASE_LOSS_SEVERITY) * 100, 1), 0.1,
                format="%.1f%%", key="upside_sev",
            ) / 100.0

        st.divider()

        # --- Monte Carlo ---
        st.subheader("Monte Carlo")

        n_sims = st.select_slider(
            "Simulations",
            options=[1_000, 2_000, 5_000, 10_000],
            value=10_000,
        )

        st.divider()

        # --- Target IRRs ---
        st.subheader("Target IRRs")
        st.caption("Used to solve for price at each return target.")

        col1, col2, col3 = st.columns(3)
        t1 = col1.number_input("IRR 1 (%)", value=10, min_value=1, max_value=50, step=1) / 100
        t2 = col2.number_input("IRR 2 (%)", value=12, min_value=1, max_value=50, step=1) / 100
        t3 = col3.number_input("IRR 3 (%)", value=15, min_value=1, max_value=50, step=1) / 100

        st.divider()

        # --- Submit ---
        st.form_submit_button(
            "Run Analysis",
            use_container_width=True,
            type="primary",
        )

    return SidebarInputs(
        vintage_year_start=vintage_year_start,
        vintage_year_end=vintage_year_end,
        status_filter=status_filter,
        purchase_price=purchase_price,
        base_cdr=base_cdr,
        base_cpr=base_cpr,
        base_loss_severity=base_loss_severity,
        stress_cdr=stress_cdr,
        stress_cpr=stress_cpr,
        stress_loss_severity=stress_loss_severity,
        upside_cdr=upside_cdr,
        upside_cpr=upside_cpr,
        upside_loss_severity=upside_loss_severity,
        n_sims=n_sims,
        target_irrs=(t1, t2, t3),
    )
