"""
tests/test_ingest.py
--------------------
Tests for data/ingest.py: schema validation and data cleaning.

validate_pool_schema() tests use synthetic DataFrames — no parquet required.
load_clean_loans() tests write a minimal synthetic parquet via tmp_path
and verify that the SQL cleaning filters are actually applied.

Run with:
  pytest tests/test_ingest.py -v
"""

import numpy as np
import pandas as pd
import pytest

from data.ingest import validate_pool_schema, load_clean_loans, STANDARD_SCHEMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_df(n: int = 5) -> pd.DataFrame:
    """Minimal valid DataFrame matching the standard schema."""
    return pd.DataFrame({
        "loan_amnt":               [10_000.0] * n,
        "funded_amnt":             [10_000.0] * n,
        "term_months":             [36] * n,
        "int_rate":                [13.5] * n,
        "installment":             [338.0] * n,
        "grade":                   ["B"] * n,
        "sub_grade":               ["B2"] * n,
        "purpose":                 ["debt_consolidation"] * n,
        "addr_state":              ["CA"] * n,
        "issue_date":              pd.to_datetime(["2015-01-01"] * n),
        "loan_status":             ["Fully Paid"] * n,
        "fico":                    [700.0] * n,
        "dti":                     [18.5] * n,
        "out_prncp":               [0.0] * n,
        "total_pymnt":             [12_000.0] * n,
        "total_rec_prncp":         [10_000.0] * n,
        "total_rec_int":           [2_000.0] * n,
        "total_rec_late_fee":      [0.0] * n,
        "recoveries":              [0.0] * n,
        "collection_recovery_fee": [0.0] * n,
        "last_pymnt_date":         pd.to_datetime(["2018-01-01"] * n),
        "mths_since_last_delinq":  [np.nan] * n,
        "annual_inc":              [60_000.0] * n,
        "revol_util":              [45.0] * n,
        "revol_util_capped":       [45.0] * n,
        "is_over_limit":           [0.0] * n,
        "emp_length":              ["5 years"] * n,
    })


def _base_raw_row(**overrides) -> dict:
    """One valid raw Lending Club row (pre-cleaning column names)."""
    row = {
        "loan_amnt":               10_000.0,
        "funded_amnt":             10_000.0,
        "term":                    " 36 months",
        "int_rate":                13.5,
        "installment":             338.0,
        "grade":                   "B",
        "sub_grade":               "B2",
        "purpose":                 "debt_consolidation",
        "addr_state":              "CA",
        "issue_d":                 "Jan-2015",
        "loan_status":             "Fully Paid",
        "fico_range_low":          695.0,
        "fico_range_high":         699.0,
        "dti":                     18.5,
        "out_prncp":               0.0,
        "total_pymnt":             12_000.0,
        "total_rec_prncp":         10_000.0,
        "total_rec_int":           2_000.0,
        "total_rec_late_fee":      0.0,
        "recoveries":              0.0,
        "collection_recovery_fee": 0.0,
        "last_pymnt_d":            "Jan-2018",
        "mths_since_last_delinq":  None,
        "annual_inc":              60_000.0,
        "revol_util":              45.0,
        "emp_length":              "5 years",
    }
    row.update(overrides)
    return row


def _write_parquet(tmp_path, rows: list[dict]) -> str:
    df = pd.DataFrame(rows)
    path = str(tmp_path / "test_loans.parquet")
    df.to_parquet(path, index=False)
    return path


# ---------------------------------------------------------------------------
# validate_pool_schema
# ---------------------------------------------------------------------------

class TestValidateSchema:
    def test_valid_df_passes(self):
        errors = validate_pool_schema(_make_valid_df(), raise_on_error=False)
        assert errors == []

    def test_missing_column_raises(self):
        df = _make_valid_df().drop(columns=["loan_amnt"])
        with pytest.raises(AssertionError, match="Missing required column"):
            validate_pool_schema(df, raise_on_error=True)

    def test_null_in_non_nullable_column_raises(self):
        df = _make_valid_df()
        df.loc[0, "loan_amnt"] = np.nan
        with pytest.raises(AssertionError, match="null values"):
            validate_pool_schema(df, raise_on_error=True)

    def test_null_in_nullable_column_passes(self):
        """mths_since_last_delinq is nullable — all NaN is fine."""
        df = _make_valid_df()
        df["mths_since_last_delinq"] = np.nan
        errors = validate_pool_schema(df, raise_on_error=False)
        assert errors == []

    def test_fico_below_300_fails(self):
        df = _make_valid_df()
        df.loc[0, "fico"] = 200.0
        errors = validate_pool_schema(df, raise_on_error=False)
        assert any("fico" in e and "below minimum" in e for e in errors)

    def test_int_rate_above_100_fails(self):
        df = _make_valid_df()
        df.loc[0, "int_rate"] = 150.0
        errors = validate_pool_schema(df, raise_on_error=False)
        assert any("int_rate" in e and "above maximum" in e for e in errors)

    def test_invalid_term_months_fails(self):
        df = _make_valid_df()
        df.loc[0, "term_months"] = 24
        with pytest.raises(AssertionError, match="term_months"):
            validate_pool_schema(df, raise_on_error=True)

    def test_implausible_total_pymnt_fails(self):
        df = _make_valid_df()
        df.loc[0, "total_pymnt"] = 25_000.0  # loan_amnt=10k, 2×=20k
        errors = validate_pool_schema(df, raise_on_error=False)
        assert any("total_pymnt" in e for e in errors)

    def test_soft_mode_collects_all_errors(self):
        """raise_on_error=False should collect multiple errors, not stop at first."""
        df = _make_valid_df().drop(columns=["loan_amnt", "int_rate", "fico"])
        errors = validate_pool_schema(df, raise_on_error=False)
        assert len(errors) >= 3


# ---------------------------------------------------------------------------
# load_clean_loans — verify SQL filters are applied
# ---------------------------------------------------------------------------

class TestLoadCleanLoans:
    def test_valid_row_passes_through(self, tmp_path):
        path = _write_parquet(tmp_path, [_base_raw_row()])
        df = load_clean_loans(path)
        assert len(df) == 1

    def test_null_issue_d_dropped(self, tmp_path):
        path = _write_parquet(tmp_path, [
            _base_raw_row(),
            _base_raw_row(issue_d=None),
        ])
        assert len(load_clean_loans(path)) == 1

    def test_null_int_rate_dropped(self, tmp_path):
        path = _write_parquet(tmp_path, [
            _base_raw_row(),
            _base_raw_row(int_rate=None),
        ])
        assert len(load_clean_loans(path)) == 1

    def test_dti_out_of_range_dropped(self, tmp_path):
        path = _write_parquet(tmp_path, [
            _base_raw_row(),
            _base_raw_row(dti=-1.0),
            _base_raw_row(dti=110.0),
        ])
        assert len(load_clean_loans(path)) == 1

    def test_policy_exception_loan_dropped(self, tmp_path):
        path = _write_parquet(tmp_path, [
            _base_raw_row(),
            _base_raw_row(loan_status="Does not meet the credit policy. Status:Fully Paid"),
        ])
        assert len(load_clean_loans(path)) == 1

    def test_implausible_total_pymnt_dropped(self, tmp_path):
        path = _write_parquet(tmp_path, [
            _base_raw_row(),
            _base_raw_row(total_pymnt=25_000.0),
        ])
        assert len(load_clean_loans(path)) == 1

    def test_leading_space_in_term_parsed_correctly(self, tmp_path):
        """' 36 months' with leading space must parse to term_months=36."""
        path = _write_parquet(tmp_path, [_base_raw_row(term=" 36 months")])
        df = load_clean_loans(path)
        assert len(df) == 1
        assert df["term_months"].iloc[0] == 36

    def test_fico_is_midpoint_of_range(self, tmp_path):
        path = _write_parquet(tmp_path, [_base_raw_row(fico_range_low=695.0, fico_range_high=699.0)])
        df = load_clean_loans(path)
        assert abs(df["fico"].iloc[0] - 697.0) < 0.01

    def test_revol_util_capped_at_100(self, tmp_path):
        path = _write_parquet(tmp_path, [_base_raw_row(revol_util=150.0)])
        df = load_clean_loans(path)
        assert df["revol_util_capped"].iloc[0] == 100.0
        assert df["is_over_limit"].iloc[0] == 1

    def test_output_has_all_schema_columns(self, tmp_path):
        path = _write_parquet(tmp_path, [_base_raw_row()])
        df = load_clean_loans(path)
        for col in STANDARD_SCHEMA:
            assert col in df.columns, f"Missing: {col}"
