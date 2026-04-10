"""
interface/db.py
---------------
SQLite persistence layer for saving and loading analysis runs.

Schema
------
runs
  id           INTEGER PRIMARY KEY AUTOINCREMENT
  name         TEXT NOT NULL
  created_at   TEXT NOT NULL  (ISO 8601)
  inputs       TEXT NOT NULL  (JSON)
  outputs      TEXT NOT NULL  (JSON)

Each run stores the full set of sidebar inputs and the computed outputs
(scenario table, Monte Carlo summary stats) so it can be replayed or
compared without re-running the engine.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "runs.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the runs table if it doesn't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                inputs     TEXT NOT NULL,
                outputs    TEXT NOT NULL
            )
        """)


def save_run(name: str, inputs: dict[str, Any], outputs: dict[str, Any]) -> int:
    """
    Persist an analysis run to SQLite.

    Parameters
    ----------
    name : str
        Human-readable label for this run (e.g. "2016 Vintage @ 85¢").
    inputs : dict
        Sidebar inputs: vintage, purchase_price, scenario params, etc.
    outputs : dict
        Computed outputs: scenario_df (as records), monte_carlo summary.

    Returns
    -------
    int
        The row id of the saved run.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (name, created_at, inputs, outputs) VALUES (?, ?, ?, ?)",
            (name, created_at, json.dumps(inputs), json.dumps(outputs)),
        )
        return cursor.lastrowid


def load_runs() -> list[dict]:
    """
    Return all saved runs, newest first.

    Returns
    -------
    list[dict]
        Each dict has keys: id, name, created_at, inputs, outputs.
        inputs and outputs are deserialized from JSON.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, inputs, outputs FROM runs ORDER BY id DESC"
        ).fetchall()

    return [
        {
            "id":         row["id"],
            "name":       row["name"],
            "created_at": row["created_at"],
            "inputs":     json.loads(row["inputs"]),
            "outputs":    json.loads(row["outputs"]),
        }
        for row in rows
    ]


def delete_run(run_id: int) -> None:
    """Delete a saved run by id."""
    with _connect() as conn:
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))


def get_run(run_id: int) -> dict | None:
    """
    Fetch a single run by id.

    Returns None if not found.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, created_at, inputs, outputs FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id":         row["id"],
        "name":       row["name"],
        "created_at": row["created_at"],
        "inputs":     json.loads(row["inputs"]),
        "outputs":    json.loads(row["outputs"]),
    }
