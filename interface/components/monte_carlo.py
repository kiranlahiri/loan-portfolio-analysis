"""
interface/components/monte_carlo.py
-------------------------------------
IRR distribution histogram and summary statistics from Monte Carlo simulation.
"""

import numpy as np
import plotly.graph_objects as go
import streamlit as st


def render(mc: dict) -> None:
    """
    Render Monte Carlo IRR histogram and summary stats.

    Parameters
    ----------
    mc : dict
        Output of cashflow.scenarios.monte_carlo(). Expected keys:
        irrs, mean, median, std, p5, p1, prob_loss, cdr_draws, cpr_draws.
    """
    st.subheader("Monte Carlo — IRR Distribution")
    st.caption(
        "CDR and CPR drawn from a bivariate normal distribution (correlation = −0.4) "
        "calibrated to 2012–2016 completed vintage spread (CDR σ = 0.98%, CPR σ = 4.7%). "
        "Represents benign-cycle vintage-to-vintage variation — not full economic cycle uncertainty. "
        "Loss severity fixed at base assumption (empirically stable across vintages)."
    )

    irrs = mc["irrs"]
    valid = irrs[~np.isnan(irrs)]

    # -------------------------------------------------------------------------
    # Summary stats
    # -------------------------------------------------------------------------
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Mean IRR",      f"{mc['mean']:.2%}")
    c2.metric("Median IRR",    f"{mc['median']:.2%}")
    c3.metric("P5 (tail)",     f"{mc['p5']:.2%}")
    c4.metric("P1 (extreme)",  f"{mc['p1']:.2%}")
    c5.metric("Prob. of Loss", f"{mc['prob_loss']:.1%}")

    # -------------------------------------------------------------------------
    # Histogram
    # -------------------------------------------------------------------------
    fig = go.Figure()

    # Split into loss (negative) and profit (positive) for colour coding
    loss_irrs   = valid[valid < 0]
    profit_irrs = valid[valid >= 0]

    bin_size = 0.005  # 0.5% bins

    if len(loss_irrs) > 0:
        fig.add_trace(go.Histogram(
            x=loss_irrs,
            xbins=dict(size=bin_size),
            name="Loss (IRR < 0)",
            marker_color="rgba(255, 71, 87, 0.75)",
            hovertemplate="IRR: %{x:.1%}<br>Count: %{y}<extra></extra>",
        ))

    if len(profit_irrs) > 0:
        fig.add_trace(go.Histogram(
            x=profit_irrs,
            xbins=dict(size=bin_size),
            name="Profit (IRR ≥ 0)",
            marker_color="rgba(74, 148, 255, 0.70)",
            hovertemplate="IRR: %{x:.1%}<br>Count: %{y}<extra></extra>",
        ))

    # Vertical lines for mean and P5
    fig.add_vline(
        x=mc["mean"], line_dash="dash", line_color="#ffeaa7", line_width=1.5,
        annotation_text=f"Mean {mc['mean']:.1%}",
        annotation_position="top right",
        annotation_font_color="#ffeaa7",
    )
    fig.add_vline(
        x=mc["p5"], line_dash="dot", line_color="#ff4757", line_width=1.2,
        annotation_text=f"P5 {mc['p5']:.1%}",
        annotation_position="top left",
        annotation_font_color="#ff4757",
    )

    fig.update_layout(
        title=f"IRR Distribution ({len(valid):,} simulations)",
        xaxis_title="IRR (annualized nominal APR)",
        yaxis_title="Simulation Count",
        barmode="overlay",
        bargap=0.02,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=380,
        margin=dict(t=60, b=40, l=60, r=20),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#e6edf3"),
        xaxis=dict(
            tickformat=".0%",
            showgrid=True,
            gridcolor="rgba(255,255,255,0.07)",
            zeroline=True,
            zerolinecolor="rgba(255,255,255,0.25)",
            zerolinewidth=1.5,
            color="#e6edf3",
        ),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)", color="#e6edf3"),
    )

    st.plotly_chart(fig, width="stretch")

    # -------------------------------------------------------------------------
    # CDR vs IRR scatter (diagnostic)
    # -------------------------------------------------------------------------
    with st.expander("CDR vs IRR scatter (diagnostic)", expanded=False):
        st.caption(
            "Each point is one simulation. Shows how sensitive IRR is to CDR assumptions. "
            "A steep negative slope means default risk is the dominant driver."
        )

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=mc["cdr_draws"],
            y=mc["irrs"],
            mode="markers",
            marker=dict(size=2, color="rgba(74, 148, 255, 0.35)"),
            hovertemplate="CDR: %{x:.1%}<br>IRR: %{y:.1%}<extra></extra>",
        ))
        fig2.update_layout(
            xaxis_title="CDR (simulated)",
            yaxis_title="IRR",
            height=300,
            margin=dict(t=20, b=40, l=60, r=20),
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font=dict(color="#e6edf3"),
            xaxis=dict(tickformat=".0%", color="#e6edf3",
                       gridcolor="rgba(255,255,255,0.07)"),
            yaxis=dict(tickformat=".0%", color="#e6edf3",
                       gridcolor="rgba(255,255,255,0.07)"),
        )
        st.plotly_chart(fig2, width="stretch")
