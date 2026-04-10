"""
interface/components/history.py
---------------------------------
Save current run to SQLite and browse / load past runs.

Workflow:
  - "Save Run" button at top of main panel → prompts for a name → persists to DB
  - "History" expander at bottom → lists saved runs with timestamp and inputs summary
  - Clicking a saved run loads its outputs back into the display
"""

import json
import pandas as pd
import streamlit as st

from interface.db import save_run, load_runs, delete_run


def render_save_button(inputs: dict, outputs: dict) -> None:
    """
    Render the Save Run control.

    Parameters
    ----------
    inputs : dict
        Serializable dict of current sidebar inputs.
    outputs : dict
        Serializable dict of current computed outputs (scenario_df as records, mc summary).
    """
    with st.expander("Save this run", expanded=False):
        name = st.text_input(
            "Run name",
            value=_default_run_name(inputs),
            help="Give this run a memorable label so you can find it later.",
        )
        if st.button("Save", type="primary"):
            run_id = save_run(name, inputs, outputs)
            st.success(f'Saved as "{name}" (id={run_id})')
            st.rerun()


def render_history() -> dict | None:
    """
    Render the run history panel.

    Returns
    -------
    dict or None
        The loaded run dict if the user clicks Load, otherwise None.
    """
    runs = load_runs()

    if not runs:
        return None

    with st.expander(f"Run History ({len(runs)} saved)", expanded=False):
        for run in runs:
            col1, col2, col3 = st.columns([4, 2, 1])

            # Timestamp — strip microseconds for readability
            ts = run["created_at"][:19].replace("T", " ")
            inp = run["inputs"]

            vintage_label = _vintage_label(inp)
            price_label   = f"{inp.get('purchase_price', 0):.0%}"

            col1.markdown(f"**{run['name']}**  \n{ts} · {vintage_label} · {price_label}")

            loaded = col2.button("Load", key=f"load_{run['id']}")
            deleted = col3.button("Del", key=f"del_{run['id']}", type="secondary")

            if deleted:
                delete_run(run["id"])
                st.rerun()

            if loaded:
                return run

    return None


def outputs_to_serializable(scenario_df: pd.DataFrame, mc: dict) -> dict:
    """
    Convert engine outputs to a JSON-serializable dict for storage.

    Parameters
    ----------
    scenario_df : pd.DataFrame
        Output of compare_scenarios().
    mc : dict
        Output of monte_carlo() — numpy arrays stripped out, only summary stats kept.
    """
    return {
        "scenario_df": scenario_df.to_dict(orient="records"),
        "monte_carlo": {
            k: float(v) for k, v in mc.items()
            if k in ("mean", "median", "std", "p5", "p1", "prob_loss")
        },
    }


def outputs_from_stored(stored: dict) -> tuple[pd.DataFrame, dict]:
    """
    Deserialize stored outputs back into usable objects.

    Returns
    -------
    tuple[pd.DataFrame, dict]
        scenario_df and mc summary dict.
    """
    scenario_df = pd.DataFrame(stored["scenario_df"])
    mc_summary  = stored["monte_carlo"]
    return scenario_df, mc_summary


def _default_run_name(inputs: dict) -> str:
    vintage = _vintage_label(inputs)
    price   = f"{inputs.get('purchase_price', 0):.0%}"
    return f"{vintage} @ {price}"


def _vintage_label(inputs: dict) -> str:
    start = inputs.get("vintage_year_start", 2007)
    end   = inputs.get("vintage_year_end",   2018)
    if start == 2007 and end == 2018:
        return "Full Pool"
    return f"{start}–{end}"
