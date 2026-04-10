"""
data/ingest.py
--------------
Dataset ingestion, schema validation, and cleaning.

This module is the Option B deliverable: a hardened data pipeline that
validates, cleans, and logs issues for any loan dataset conforming to
a standard schema. The cash flow engine never touches this layer.

Supported datasets:
  - Lending Club 2007-2018Q4 (accepted_2007_to_2018Q4.parquet)

Adding a new dataset:
  1. Define its raw column mapping in SCHEMA_* constants
  2. Write a load_* function that maps raw columns to the standard schema
  3. Pass the result through validate_pool_schema() before returning

Standard schema (columns all load_* functions must produce):
  loan_amnt       : float  — original loan amount
  funded_amnt     : float  — amount actually funded
  term_months     : int    — loan term (36 or 60)
  int_rate        : float  — annual interest rate (percent, e.g. 13.5)
  installment     : float  — monthly payment amount
  grade           : str    — risk grade (A-G)
  sub_grade       : str    — risk sub-grade (A1-G5)
  purpose         : str    — loan purpose category
  addr_state      : str    — borrower state (2-letter code)
  issue_date      : datetime — loan origination date
  loan_status     : str    — current/terminal loan status
  fico            : float  — average of FICO range bounds
  dti             : float  — debt-to-income ratio (percent)
  out_prncp       : float  — outstanding principal balance
  total_pymnt     : float  — total amount paid to date
  total_rec_prncp : float  — total principal received
  total_rec_int   : float  — total interest received
  total_rec_late_fee : float — total late fees received
  recoveries      : float  — post-charge-off recoveries
  collection_recovery_fee : float — collection fees
  last_pymnt_date : datetime or NaT — date of last payment
  mths_since_last_delinq : float or NaN — months since last delinquency
"""

import logging
import duckdb
import pandas as pd
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level cache — loaded once, reused by notebook, Streamlit app, and CLI
_loans_cache: Optional[pd.DataFrame] = None
_loans_path:  Optional[str] = None


def get_loans(path: str = "accepted_2007_to_2018Q4.parquet") -> pd.DataFrame:
    """
    Load, cache, and return the clean loans DataFrame.

    On first call, loads and validates the dataset (~15 seconds for 2.2M rows).
    On subsequent calls, returns the cached DataFrame immediately.

    Also registers the DataFrame as a DuckDB in-memory table named 'loans',
    so callers can run DuckDB SQL queries against it directly:
        duckdb.sql("SELECT COUNT(*) FROM loans").fetchone()

    Parameters
    ----------
    path : str
        Path to the Lending Club parquet file. Only used on first call —
        subsequent calls return the cache regardless of path.

    Returns
    -------
    pd.DataFrame
        Cleaned, validated loans DataFrame.
    """
    global _loans_cache, _loans_path

    if _loans_cache is not None:
        logger.debug("Returning cached loans DataFrame")
        return _loans_cache

    logger.info(f"Loading loans from {path} (first call — caching result)")
    df = load_clean_loans(path)
    validate_pool_schema(df, dataset_label="Lending Club", raise_on_error=True)

    # Register as DuckDB table so SQL queries work anywhere in the codebase
    duckdb.register("loans", df)
    logger.info("Registered 'loans' as DuckDB in-memory table")

    _loans_cache = df
    _loans_path  = path
    return df


# ---------------------------------------------------------------------------
# Standard schema — column name → (dtype, nullable, valid_range)
# ---------------------------------------------------------------------------

STANDARD_SCHEMA = {
    "loan_amnt":              (float,  False, (0, None)),
    "funded_amnt":            (float,  True,  (0, None)),
    "term_months":            (int,    False, (1, 360)),
    "int_rate":               (float,  False, (0, 100)),
    "installment":            (float,  True,  (0, None)),
    "grade":                  (str,    True,  None),
    "sub_grade":              (str,    True,  None),
    "purpose":                (str,    True,  None),
    "addr_state":             (str,    True,  None),
    "issue_date":             ("datetime", False, None),
    "loan_status":            (str,    False, None),
    "fico":                   (float,  True,  (300, 850)),
    "dti":                    (float,  True,  (0, None)),
    "out_prncp":              (float,  True,  (0, None)),
    "total_pymnt":            (float,  True,  (0, None)),
    "total_rec_prncp":        (float,  True,  (0, None)),
    "total_rec_int":          (float,  True,  (0, None)),
    "total_rec_late_fee":     (float,  True,  None),        # can be negative (fee reversals)
    "recoveries":             (float,  True,  (0, None)),
    "collection_recovery_fee":(float,  True,  (0, None)),
    "last_pymnt_date":        ("datetime", True, None),
    "mths_since_last_delinq": (float,  True,  (0, None)),
    "annual_inc":             (float,  True,  (0, None)),
    "revol_util":             (float,  True,  None),       # raw — can exceed 100 (balance > credit limit)
    "revol_util_capped":      (float,  True,  (0, 100)),   # capped at 100 for engine inputs
    "is_over_limit":          (float,  True,  (0, 1)),     # 1 if borrower is over credit limit
    "emp_length":             (str,    True,  None),       # employment length category (< 1 year to 10+ years)
}


# ---------------------------------------------------------------------------
# Lending Club ingestion
# ---------------------------------------------------------------------------

def load_clean_loans(path: str) -> pd.DataFrame:
    """
    Load and clean the Lending Club loan dataset from a parquet file.

    Applies all known data quality fixes at query time — the raw parquet
    file is never modified. Every exclusion is documented with a reason
    and logged.

    Data quality issues handled (see CLAUDE.md for full documentation):
      - Null issue_d (33 rows)         : drop — fully corrupt
      - Invalid term (leading space)   : TRIM before parsing
      - Null int_rate (1,744 rows)     : drop — cannot compute WAC
      - DTI out of range (2,600 rows)  : filter — impossible values
      - Policy exception loans (2,749) : exclude — not comparable
      - total_pymnt > 2× loan_amnt (1) : drop — implausible

    Parameters
    ----------
    path : str
        Path to the Lending Club parquet file.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame conforming to the standard schema.
        ~2,253,644 rows on the full dataset.
    """
    logger.info(f"Loading Lending Club data from: {path}")

    df = duckdb.sql(f"""
        SELECT
            loan_amnt,
            funded_amnt,
            CAST(SPLIT_PART(TRIM(term), ' ', 1) AS INTEGER)  AS term_months,
            int_rate,
            installment,
            grade,
            sub_grade,
            purpose,
            addr_state,
            STRPTIME(issue_d, '%b-%Y')                        AS issue_date,
            loan_status,
            (fico_range_low + fico_range_high) / 2.0          AS fico,
            dti,
            out_prncp,
            total_pymnt,
            total_rec_prncp,
            total_rec_int,
            total_rec_late_fee,
            recoveries,
            collection_recovery_fee,
            CASE
                WHEN last_pymnt_d IS NOT NULL
                THEN STRPTIME(last_pymnt_d, '%b-%Y')
                ELSE NULL
            END                                               AS last_pymnt_date,
            mths_since_last_delinq,
            annual_inc,
            revol_util,
            LEAST(revol_util, 100.0)                           AS revol_util_capped,
            CASE WHEN revol_util > 100 THEN 1 ELSE 0 END       AS is_over_limit,
            emp_length

        FROM '{path}'

        WHERE
            issue_d IS NOT NULL
            AND TRIM(term) IN ('36 months', '60 months')
            AND int_rate IS NOT NULL
            AND dti >= 0
            AND loan_status NOT LIKE 'Does not meet%'
            AND total_pymnt <= loan_amnt * 2

    """).df()

    logger.info(f"Loaded {len(df):,} loans after cleaning")
    return df


def validate_pool_schema(
    df: pd.DataFrame,
    dataset_label: str = "dataset",
    raise_on_error: bool = True,
) -> list[str]:
    """
    Validate a DataFrame against the standard pool schema.

    Checks:
      - Required columns are present
      - Non-nullable columns have no nulls
      - Numeric columns are within valid ranges
      - term_months is one of [36, 60]
      - int_rate is in (0, 100)
      - fico is in [300, 850] where present

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to validate (output of a load_* function).
    dataset_label : str
        Label for logging messages (e.g. "Lending Club 2016").
    raise_on_error : bool
        If True (default), raises AssertionError on first failure.
        If False, collects all errors and returns them as a list.

    Returns
    -------
    list[str]
        List of validation error messages (empty if all checks pass).

    Raises
    ------
    AssertionError
        If raise_on_error=True and any validation check fails.
    """
    errors = []

    def _fail(msg):
        errors.append(msg)
        if raise_on_error:
            raise AssertionError(f"[{dataset_label}] Schema validation failed: {msg}")
        else:
            logger.warning(f"[{dataset_label}] {msg}")

    # Check required columns exist
    for col, (dtype, nullable, valid_range) in STANDARD_SCHEMA.items():
        if col not in df.columns:
            _fail(f"Missing required column: '{col}'")
            continue

        # Check nullability
        null_count = df[col].isna().sum()
        if not nullable and null_count > 0:
            _fail(f"Column '{col}' has {null_count:,} null values (not allowed)")

        # Check numeric range
        if valid_range is not None and dtype in (float, int):
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            lo, hi = valid_range
            if lo is not None and (series < lo).any():
                n = (series < lo).sum()
                _fail(f"Column '{col}' has {n:,} values below minimum {lo}")
            if hi is not None and (series > hi).any():
                n = (series > hi).sum()
                _fail(f"Column '{col}' has {n:,} values above maximum {hi}")

    # Lending-Club-specific checks
    if "term_months" in df.columns:
        invalid_term = ~df["term_months"].isin([36, 60])
        if invalid_term.any():
            _fail(f"term_months has {invalid_term.sum():,} values not in [36, 60]")

    if "loan_amnt" in df.columns and "total_pymnt" in df.columns:
        implausible = df["total_pymnt"] > df["loan_amnt"] * 2
        if implausible.any():
            _fail(f"total_pymnt > 2× loan_amnt for {implausible.sum():,} loans")

    if not errors:
        logger.info(f"[{dataset_label}] Schema validation passed: {len(df):,} rows")

    return errors


def validate_loans(df: pd.DataFrame) -> None:
    """
    Convenience wrapper — validates and prints a summary.
    Raises AssertionError if validation fails.
    """
    validate_pool_schema(df, dataset_label="Lending Club", raise_on_error=True)

    print(f"Validation passed: {len(df):,} loans loaded")
    print(f"Columns: {list(df.columns)}")
    print(f"\nLoan status breakdown:")
    print(df["loan_status"].value_counts())
