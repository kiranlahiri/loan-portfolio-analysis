"""
interface/components/cashflow_chart.py
----------------------------------------
Plotly stacked area chart of projected monthly cash flows.

Shows four components stacked:
  - Interest income
  - Scheduled principal
  - Prepayments
  - Losses (shown as negative / red)
"""

import numpy as np
import plotly.graph_objects as go
import streamlit as st


def render(cf: dict, scenario_label: str = "Base") -> None:
    """
    Render a stacked area chart of monthly cash flow projections.

    Parameters
    ----------
    cf : dict
        Output of cashflow.engine.project() — numpy arrays keyed by:
        interest, principal, prepayments, defaults, losses, net_cf, balance_sod.
    scenario_label : str
        Label for the chart title (e.g. "Base", "Stress", "Upside").
    """
    months = np.arange(1, len(cf["interest"]) + 1)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=months, y=cf["interest"],
        name="Interest",
        stackgroup="positive",
        fillcolor="rgba(74, 148, 255, 0.55)",
        line=dict(color="rgba(74, 148, 255, 0.9)", width=0.5),
        hovertemplate="Month %{x}<br>Interest: $%{y:,.0f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=months, y=cf["principal"],
        name="Scheduled Principal",
        stackgroup="positive",
        fillcolor="rgba(46, 213, 115, 0.45)",
        line=dict(color="rgba(46, 213, 115, 0.8)", width=0.5),
        hovertemplate="Month %{x}<br>Scheduled Principal: $%{y:,.0f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=months, y=cf["prepayments"],
        name="Prepayments",
        stackgroup="positive",
        fillcolor="rgba(162, 155, 254, 0.45)",
        line=dict(color="rgba(162, 155, 254, 0.8)", width=0.5),
        hovertemplate="Month %{x}<br>Prepayments: $%{y:,.0f}<extra></extra>",
    ))

    # Losses shown as negative — separate stack group so they go below zero
    fig.add_trace(go.Scatter(
        x=months, y=-cf["losses"],
        name="Losses",
        stackgroup="negative",
        fillcolor="rgba(255, 71, 87, 0.50)",
        line=dict(color="rgba(255, 71, 87, 0.8)", width=0.5),
        hovertemplate="Month %{x}<br>Losses: $%{y:,.0f}<extra></extra>",
    ))

    # Net cash flow line overlay
    fig.add_trace(go.Scatter(
        x=months, y=cf["net_cf"],
        name="Net CF",
        mode="lines",
        line=dict(color="#ffeaa7", width=1.5, dash="dot"),
        hovertemplate="Month %{x}<br>Net CF: $%{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title=f"Monthly Cash Flow Projection — {scenario_label} Scenario",
        xaxis_title="Month",
        yaxis_title="Cash Flow ($)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        height=420,
        margin=dict(t=60, b=40, l=60, r=20),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#e6edf3"),
        xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)", color="#e6edf3"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)", zeroline=True,
                   zerolinecolor="rgba(255,255,255,0.25)", color="#e6edf3"),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Summary stats below chart
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Interest",    f"${cf['interest'].sum():,.0f}")
    col2.metric("Total Principal",   f"${(cf['principal'] + cf['prepayments']).sum():,.0f}")
    col3.metric("Total Losses",      f"${cf['losses'].sum():,.0f}")
    col4.metric("Net Cash Flow",     f"${cf['net_cf'].sum():,.0f}")
