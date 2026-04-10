# Technical Writeup
## Aravalli Capital — Loan Portfolio Investment Analysis Tool

---

## 1. Architecture

The codebase is organized into four layers, each with a single responsibility:

```
aravalli-capital/
├── data/
│   ├── ingest.py        # load_clean_loans(), validate_pool_schema()
│   └── schema.py        # column definitions and valid ranges
├── cashflow/
│   ├── engine.py        # pure pool-level projection (no pandas, no I/O)
│   ├── irr.py           # IRR solver, price solver (numpy_financial)
│   └── scenarios.py     # base/stress/upside scenario wrapper + Monte Carlo
├── interface/
│   ├── app.py           # Streamlit web application
│   ├── api.py           # FastAPI REST API
│   └── components/      # Streamlit UI components
├── tests/
│   ├── test_cashflow.py # single-loan known-answer tests
│   └── test_ingest.py   # schema validation and data cleaning tests
├── docs/
│   └── api.md           # REST API documentation
├── examples/
│   └── api_example.py   # complete API workflow example
└── portfolio_analysis.ipynb  # exploratory analysis and Part 1 outputs
```

**Data layer** (`data/`) handles all I/O and cleaning. `load_clean_loans()` executes a DuckDB SQL query directly against the parquet file, applies all filters at query time, and returns a clean DataFrame. The raw parquet is never modified. Schema validation is separated into `validate_pool_schema()` so it can be run independently.

**Cash flow engine** (`cashflow/engine.py`) is a pure function: it takes scalar inputs (balance, WAC, WAM, CDR, CPR, loss severity) and returns a month-by-month cash flow array. It has no dependency on pandas, DuckDB, or any I/O layer. This makes it independently testable and fast — the engine runs in microseconds on any pool size because it operates on pool-level aggregates, not loan-level records.

**Interface layer** (`interface/`) consists of two independent consumers of the engine: a Streamlit web application (`app.py`) and a FastAPI REST API (`api.py`). Both import from `data/` and `cashflow/` but not from each other, maintaining clean separation. The REST API exposes the same projection, IRR, price-solving, and scenario analysis capabilities as the Streamlit app, allowing external systems to call the engine programmatically.

**Analysis notebook** (`portfolio_analysis.ipynb`) contains all Part 1 portfolio analytics and is a primary deliverable alongside the module code. It imports from `data/` and `cashflow/` rather than duplicating logic inline — the notebook is a consumer of the module layer, not a parallel implementation of it. The notebook covers: pool stratifications (grade, term, purpose, geography, vintage); credit metrics (WAC, WALA, WAM, FICO, DTI); vintage selection validation via Population Stability Index (PSI); CDR, CPR, and loss severity analysis across completed vintages; Delta method extrapolation for 2017–2018 vintages; delinquency analysis including staleness check and roll-to-loss approximation; and a synthetic cohort transition matrix. The analysis notebook was kept separate from the interface deliberately — it is reproducible, peer-reviewable analysis that an investor or counterparty can audit step by step, whereas the Streamlit app is an interactive tool for scenario exploration.

---

## 2. Data Issues Found and Handling

The raw Lending Club dataset (2,260,701 loans) contains several quality issues. All cleaning is applied at query time in `load_clean_loans()`. The raw parquet is never modified.

| Issue | Count | Handling | Rationale |
|-------|-------|----------|-----------|
| Null `issue_d` | 33 | Drop | Fully corrupt rows — no origination date means no vintage assignment possible |
| Invalid `term` (leading space, non-standard) | ~33 | Filter to `TRIM(term) IN ('36 months', '60 months')` | Only two valid terms exist per Lending Club documentation |
| Null `int_rate` | 1,744 | Drop | Cannot compute WAC without interest rate |
| DTI < 0 | 2 | Drop | Mathematically impossible — negative DTI has no valid interpretation |
| DTI > 100 | ~2,561 | **Retain** | Real over-leveraged borrowers concentrated in 2017–2018 vintages (0.03–0.32% of those years). Excluding them would remove the highest-risk tail and understate CDR for recent pools. PSI analysis confirmed essentially zero presence in 2012–2016, so the baseline window is unaffected. |
| "Does not meet credit policy" loans | 2,749 | Exclude | Policy change mid-dataset; not comparable to standard originations |
| `total_pymnt > loan_amnt × 2` | 1 | Drop | Implausible payment record suggesting data corruption |
| **Total excluded** | **4,562 (0.2%)** | | |
| **Loans loaded** | **2,256,139** | | |

**Key data note — `recoveries` column:** Per Moody's Consumer Loan ABS Methodology §6.4.2, recoveries reported in consumer loan data include post-charge-off collections of accrued interest and fees, not just principal. The Lending Club `recoveries` column follows this convention. As a result, our reported recovery rate (8.24%) slightly overstates the true *principal* recovery rate. This is documented in the loss severity analysis and affects the interpretation of that metric.

**Key data note — `mths_since_last_delinq`:** This column records the months since the borrower's most recent delinquency in their *pre-origination credit history* (credit bureau snapshot at application time). It does not record delinquency events during the Lending Club loan. This distinction is critical for the delinquency analysis (§5 below).

**`revol_util` over 100%:** 7,302 loans have revolving utilization above 100%, which occurs when a borrower's balance exceeds their credit limit. Rather than silently capping these values, we retain the raw `revol_util` column (investor signal — high utilization is a credit stress indicator), add a `revol_util_capped` column (clamped to 100 for use as a model input), and add an `is_over_limit` binary flag. This preserves the information while maintaining engine stability.

---

## 3. Metric Definitions

Pool-level credit metrics (WAC, WALA, WAM, FICO, DTI) are weighted by `out_prncp` (outstanding principal balance) for the active pool, reflecting the exposure on money currently at risk. Performance metrics (CDR, CPR, loss severity) use `loan_amnt` (original balance) as the denominator, the standard convention for vintage analysis. Full computed results are in `portfolio_analysis.ipynb`.

### 3.1 Credit Metrics (Active Pool)

**WAC (Weighted Average Coupon)**
```
WAC = Σ(int_rate_i × out_prncp_i) / Σ(out_prncp_i)
```
Weighted by current balance rather than origination balance — a loan with more principal remaining has proportionally more influence on the pool's blended rate.

**WALA (Weighted Average Loan Age)**
```
WALA = Σ(months_since_origination_i × out_prncp_i) / Σ(out_prncp_i)
Reference date: 2018-10-01 (approximate dataset cutoff)
```

**WAM (Weighted Average Maturity)**
```
WAM = Σ(remaining_months_i × out_prncp_i) / Σ(out_prncp_i)
remaining_months_i = MAX(0, term_months_i − loan_age_months_i)
```
Sanity check: WAM + WALA = weighted average term (verified in notebook).

**Average FICO**
```
Avg FICO = Σ(fico_midpoint_i × out_prncp_i) / Σ(out_prncp_i)
fico_midpoint_i = (fico_range_low_i + fico_range_high_i) / 2
```
LC reports FICO as a 5-point band; midpoint approximation introduces negligible error.

**Average DTI**
```
Avg DTI = Σ(dti_i × out_prncp_i) / Σ(out_prncp_i)
```

### 3.2 Performance Metrics (Completed Vintages 2012–2016)

**Vintage window selection:** Performance analysis is restricted to 2012–2016 vintages, determined using Population Stability Index (PSI) across six pool characteristics (FICO, DTI, annual income, revolving utilization, loan purpose, employment length). PSI revealed a regime break at the 2011→2012 transition (PSI > 0.25 on 4 of 6 variables), reflecting tightened underwriting standards post-crisis. All PSI values within 2012–2016 are below 0.10 (stable population). PSI was also run on 2016→2017 and 2017→2018 transitions to validate that the timing curve derived from 2012–2016 can be applied to extrapolate incomplete vintage CDRs.

**CDR (Cumulative Default Rate)**
```
CDR = Σ(loan_amnt where loan_status IN ('Charged Off', 'Default'))
      / Σ(loan_amnt)
```
Balance-weighted using original loan amount. Definition per Moody's §3. Base assumption (17.55%) is the loan-count credibility-weighted mean across 2012–2016 vintages.

For incomplete vintages (2017–2018), we apply the Moody's Delta method (Appendix 1): `lifetime_CDR = observed_CDR / timing_curve_value[vintage_age]`, where the timing curve is derived empirically from 2012–2016 completed vintages.

**CPR (Cumulative Prepayment Rate)**
```
CPR = Σ(loan_amnt where prepaid) / Σ(loan_amnt)
A loan is prepaid if: loan_status = 'Fully Paid'
                   AND last_pymnt_date < scheduled_maturity_date
```
We use lifetime cumulative CPR rather than the SMM-based annualized rate used in MBS analysis, which is the appropriate measure for static pool consumer ABS cash flow projection.

**Loss Severity**
```
Loss Severity = (defaulted_balance − recoveries) / defaulted_balance
```
Where `defaulted_balance` = `loan_amnt` for charged-off loans. Per Moody's §6.4.2, `recoveries` includes interest and fees, slightly overstating principal recovery. Loss severity was empirically stable across all completed vintages, reflecting the structural nature of unsecured loan recovery rates.

**Delinquency Analysis**

A traditional roll rate matrix requires monthly panel data — each loan observed at multiple points in time so that transitions between delinquency states (current → 30 DPD → 60 DPD → charge-off) can be directly measured. The LC dataset is a static snapshot: each loan appears once, at a single point in time. Month-to-month state transitions cannot be observed.

To address this, we constructed a **synthetic cohort transition matrix** using cross-sectional age stratification. Because PSI analysis confirmed that 2012–2018 vintages are drawn from a stable borrower population (all consecutive vintage-pair PSI values below 0.10), loans of different vintages observed at different ages can be treated as lifecycle proxies for the same cohort. A 2013 loan observed at age 36 months tells us what a 2016 loan will look like at age 36 months. This gives full lifecycle coverage from months 1–72 across all loan ages. The resulting matrix shows the implied status distribution at each age bucket and the implied transition rates between adjacent buckets — approximating the roll rate structure that panel data would produce directly.

We also conducted a **staleness analysis** using `last_pymnt_d` to identify delinquent loans whose most recent payment was more than 150 days before the dataset snapshot — a proxy for unreported charge-offs. Result: zero stale loans, confirming LC's charge-off processing was current at the snapshot date.

The `mths_since_last_delinq` column was evaluated as a potential delinquency signal but discarded. It records months since the borrower's last delinquency in their *pre-origination credit history* (credit bureau snapshot at application time), not events during the LC loan. CDR gradient analysis across delinquency recency buckets confirmed the column carries no within-loan signal — the gradient was flat across all loan status categories, inconsistent with what a true delinquency transition variable should show.

---

## 4. Cash Flow Engine

The engine (`cashflow/engine.py`) is a pure function: given six scalar inputs — balance, WAC, WAM, CDR, CPR, loss severity — it returns a month-by-month array of cash flows. It has no dependency on pandas, DuckDB, or any I/O layer. This design was deliberate: decoupling the engine from the data and interface layers means it can be tested in isolation, called from the Streamlit app, and reused for any dataset that produces a `PoolSnapshot`.

The projection loop follows Moody's Consumer Loan ABS Methodology §6:

1. **Defaults**: Monthly default rate is computed using the SMM convention — `SMM_CDR = 1 - (1 - CDR)^(1/12)` — applied to the current balance scaled by a timing curve. The timing curve front-loads defaults to months 12–24 per Moody's §6.3, reflecting the empirically observed pattern that consumer loan defaults peak in the second year.
2. **Prepayments**: Monthly prepayment rate uses the same SMM convention — `SMM_CPR = 1 - (1 - CPR)^(1/12)` — applied to the balance remaining after defaults.
3. **Scheduled payments**: The standard annuity formula computes the monthly payment on the surviving balance at the current WAC/12 rate.
4. **Losses**: `loss = defaults × loss_severity`. Recoveries are implicit in the severity assumption.

**IRR and price solver** (`cashflow/irr.py`): IRR is the discount rate that makes the NPV of the projected cash flow stream equal to the purchase price. We use `numpy_financial.irr()` on the full cash flow array (prepending the t=0 outflow) and annualize as `monthly_irr × 12` — nominal APR convention, consistent with how WAC is applied in the engine. The price solver uses bisection between 1 cent and 200% of UPB, which guarantees convergence since IRR is monotonically decreasing in price.

**Testing**: Known-answer tests validate the engine against analytically computable cases: (1) a single loan with no defaults or prepayments — IRR must equal WAC exactly; (2) CPR = 100% — pool must extinguish in one month; (3) CDR = 100% with full severity — all cash flows are zero after month 1. These tests caught two bugs during development: incorrect use of the compound interest formula instead of SMM for monthly rate conversion, and annualization of IRR using EAR instead of nominal APR.

---

## 5. Part 3 Extensions

**Option A — Streamlit Dashboard**

The Streamlit application (`interface/app.py`) provides an interactive browser-based interface for the full analysis workflow. The sidebar exposes: vintage range selection (2007–2018), loan status filter, purchase price slider, and individually adjustable CDR/CPR/loss severity sliders for all three scenarios. The main panel renders a pool summary (balance, WAC, WAM, FICO, DTI metrics), a color-coded scenario comparison table (Base in blue, Stress in red, Upside in green; IRR colored by threshold), tabbed cash flow projection charts per scenario, a Monte Carlo IRR distribution histogram, and an Excel export covering all three outputs across multiple sheets.

The Streamlit implementation uses `st.cache_data` throughout to avoid recomputing expensive steps (data loading, pool filtering, pool metrics) when only downstream parameters change. The vintage filter and data source selector sit outside the form so they trigger immediate reruns; scenario and purchase price inputs are batched inside a form so nothing fires until the analyst clicks "Run Analysis."

**Option C — REST API**

The REST API (`interface/api.py`) is built with FastAPI and exposes the same engine capabilities as the Streamlit app as a programmable interface. Endpoints: `GET /health`, `GET /defaults`, `POST /pool`, `POST /project`, `POST /irr`, `POST /solve-price`, `POST /scenarios`. All endpoints except `/health` require an API key via `X-API-Key` header. Rate limiting is applied via slowapi (20 req/min on `/pool`, 100 req/min elsewhere).

The intended workflow mirrors the Streamlit app: call `/pool` to load and summarize a vintage range, then pass the returned pool parameters into `/scenarios`, `/irr`, or `/solve-price`. This allows external systems — risk management tools, portfolio monitoring scripts, other analytical platforms — to access the projection engine without running the UI. Static API documentation is in `docs/api.md`; a complete annotated workflow example is in `examples/api_example.py`.

**Monte Carlo**

The Monte Carlo simulation draws CDR and CPR from a bivariate normal distribution (correlation = −0.4) rather than independently. The negative correlation reflects the economic relationship between defaults and prepayments: in a credit downturn, CDR rises as borrowers default while CPR falls as tighter underwriting prevents refinancing. Uncertainty parameters (CDR σ = 0.98%, CPR σ = 4.7%) are fixed to the 2012–2016 completed vintage calibration and do not vary with the user's vintage selection — this is an explicit design choice, clearly labeled in the UI. The simulation represents benign-cycle vintage-to-vintage variation, not full economic cycle uncertainty. Loss severity is not simulated; it was empirically stable at 91–92% across all completed vintages, reflecting the structural nature of unsecured loan recovery rates.

---

## 6. Performance


The full dataset (2,253,644 loans) is never loaded into memory as a DataFrame. `load_clean_loans()` in `data/ingest.py` executes a DuckDB SQL query directly against the parquet file, applying all filters at query time. DuckDB's columnar execution engine reads only the columns needed for a given query, making stratification queries on 2.2M loans run in under two seconds on a laptop. The raw parquet file is never modified.

The cash flow engine operates on pool-level aggregates — six scalar inputs regardless of whether the underlying pool contains 100 loans or 1,000,000. Runtime is determined by WAM (number of projection months), not pool size. A 39-month projection runs in microseconds. This means the Streamlit app can recompute IRR interactively on every parameter change with no perceptible lag.

---

## 7. Trade-offs and Limitations

**Synthetic cohort vs. true roll rates**: The delinquency transition matrix is constructed from cross-sectional age stratification rather than observed month-to-month transitions. This is a data limitation (static snapshot), not a methodological choice. The synthetic cohort approach is valid only because PSI analysis confirmed population stability across vintages; without that validation, the cross-sectional proxy would not be defensible.

**CDR stress scenario**: The stress scenario uses a 2× CDR multiplier — a documented industry convention. Empirical calibration from 2007–2009 recession vintages was attempted but not feasible: the sample (n=6,529 loans) is too small, and early LC approved only its highest-quality borrowers, making those vintages unrepresentative of a stressed environment. All three scenario parameters (CDR, CPR, loss severity) use the same convention-based methodology to maintain internal consistency.

**Pool-level engine**: The engine aggregates all loans into six pool-level parameters. This is standard for ABS cash flow modeling and is what Moody's §6 describes. The trade-off is that loan-level heterogeneity (e.g. the tail of high-grade vs. low-grade loans within a vintage) is not captured. A loan-level simulation would require iterating over 2M+ records per projection, which is not practical for interactive use.

**Streamlit vs. a more robust interface**: Streamlit was chosen for speed of development and analyst usability. The trade-off is that it is not easily embeddable and has limited state management. The REST API (Option C) addresses the programmability gap — external systems can call the engine without running the UI — but a production deployment would benefit from a more robust web framework and authentication model.

---

## 8. What's Next

**Through-the-cycle CDR**: The base CDR (17.55%) is a point-in-time benign-cycle estimate from 2012–2016, a period of above-average credit performance. A through-the-cycle estimate would blend this with stressed assumptions weighted by historical recession frequency — producing a more conservative long-run default expectation appropriate for hold-to-maturity analysis.

**Loan-level grade stratification in scenarios**: The current engine applies a single CDR/CPR to the whole pool. Grade-level CDR curves (A: 5%, G: 44%) are already computed in Part 1. Passing grade composition as an input and applying grade-specific CDRs would materially improve projection accuracy for mixed-grade pools.

**Delta method extrapolation in the pool adapter**: `cashflow/pool.py` falls back to the base CDR assumption for incomplete vintages (2017–2018). A more rigorous approach would apply the Moody's Appendix 1 Delta method directly in the adapter, using the empirical timing curve to extrapolate lifetime CDR from the observed-to-date rate. The timing curve infrastructure already exists in the engine.

**Through-the-cycle CDR in Monte Carlo**: The Monte Carlo uncertainty parameters are calibrated to 2012–2016 benign-cycle vintage spread. A more complete simulation would widen the CDR distribution to reflect recession scenarios (e.g., using a mixture model combining the benign-cycle distribution with a stressed distribution weighted by historical recession frequency), producing tail risk estimates that extend beyond the observed vintage variation.

