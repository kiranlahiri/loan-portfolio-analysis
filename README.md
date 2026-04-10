# Loan Portfolio Analysis Tool
**Aravalli Capital — Technical Assessment**

A loan portfolio investment analysis tool built on the Lending Club public dataset (~2.2M loans, 2007–2018Q4). Models consumer loan cash flows, IRR, and scenario outcomes for a credit investor evaluating a pool for purchase.

---

## What It Does

- **Portfolio analytics**: Pool stratifications (grade, term, purpose, geography, vintage), credit metrics (WAC, WALA, WAM, FICO, DTI), and performance metrics by vintage (CDR, CPR, loss severity, delinquency analysis)
- **Cash flow engine**: Month-by-month projection of principal, interest, prepayments, and losses; IRR at a given purchase price; price solver for a target IRR
- **Scenario comparison**: Base / stress / upside IRR and bid price comparison with Monte Carlo IRR distribution
- **Streamlit dashboard**: Interactive browser UI — vintage filter, purchase price slider, adjustable scenario assumptions, Excel export
- **REST API**: Programmatic access to the same engine via FastAPI

---

## Project Structure

```
aravalli-capital/
├── data/
│   └── ingest.py            # Data loading, cleaning, schema validation
├── cashflow/
│   ├── engine.py            # Pure cash flow projection (no I/O dependencies)
│   ├── irr.py               # IRR solver, price solver
│   ├── pool.py              # PoolSnapshot dataclass and pool builder
│   └── scenarios.py         # Base/stress/upside scenarios, Monte Carlo
├── interface/
│   ├── app.py               # Streamlit web application
│   ├── api.py               # FastAPI REST API
│   └── components/          # Streamlit UI components
├── tests/
│   ├── test_cashflow.py     # Known-answer engine and IRR tests
│   └── test_ingest.py       # Schema validation and data cleaning tests
├── docs/
│   └── api.md               # REST API documentation
├── examples/
│   └── api_example.py       # Complete API workflow example
└── portfolio_analysis.ipynb # Part 1 analysis notebook
```

---

## Setup

**Prerequisites**: Python 3.10+, the Lending Club parquet file (`accepted_2007_to_2018Q4.parquet`) in the project root.

**Install dependencies:**
```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Running the Streamlit App

```bash
streamlit run interface/app.py
```

Opens at `http://localhost:8501`. The app loads the parquet file on first run (~15 seconds for 2.2M loans), then caches it for the session.

**What you can do:**
- Filter to any vintage range (2007–2018) using the sidebar slider
- Adjust purchase price and scenario assumptions (CDR, CPR, loss severity)
- View pool summary metrics, scenario IRR comparison, cash flow projections, and Monte Carlo distribution
- Export the full analysis to Excel

---

## Running the Analysis Notebook

```bash
jupyter lab
```

Opens at `http://localhost:8888`. Open `portfolio_analysis.ipynb` — this is the Part 1 deliverable covering all portfolio analytics, metric definitions, PSI vintage validation, CDR/CPR/loss severity analysis, Delta method extrapolation, and delinquency analysis.

The notebook imports from the `data/` and `cashflow/` modules rather than defining logic inline. The parquet file must be in the project root before running.

---

## Running the REST API

```bash
pip install fastapi uvicorn slowapi
uvicorn interface.api:app --reload
```

API starts at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

All endpoints except `/health` require the header `X-API-Key: dev-key-aravalli`.

**Typical workflow:**
```bash
# 1. Load pool parameters for a vintage range
curl -X POST http://localhost:8000/pool \
  -H "X-API-Key: dev-key-aravalli" \
  -H "Content-Type: application/json" \
  -d '{"vintage_year_start": 2014, "vintage_year_end": 2016}'

# 2. Run scenario comparison
curl -X POST http://localhost:8000/scenarios \
  -H "X-API-Key: dev-key-aravalli" \
  -H "Content-Type: application/json" \
  -d '{"balance": 1086177772.10, "wac": 0.146948, "wam": 25, "purchase_price": 0.85}'
```

See `docs/api.md` for full endpoint reference and `examples/api_example.py` for a complete Python workflow.

---

## Running Tests

```bash
pytest tests/ -v
```

46 tests covering the cash flow engine (known-answer cases: IRR = WAC at par, full prepayment, full default), IRR/price solver, and data pipeline schema validation.

---

## Data

The Lending Club dataset (`accepted_2007_to_2018Q4.parquet`) is not included in this repository due to file size. Download it from [Kaggle](https://www.kaggle.com/datasets/wordsforthewise/lending-club) and convert to parquet using `convert.py`:

```bash
python convert.py
```

The data pipeline excludes ~7,057 loans (0.3%) with quality issues (null origination dates, invalid terms, missing interest rates, implausible DTI, policy-exception loans). All cleaning is applied at query time — the raw file is never modified.

---

## Key Design Decisions

**Cash flow engine is pure**: `cashflow/engine.py` takes six scalar inputs and returns cash flow arrays. No pandas, no I/O. This makes it independently testable and callable from both the Streamlit app and the REST API without modification.

**DuckDB for data layer**: SQL queries execute directly against the parquet file. The 2.2M-row dataset never fully loads into memory as a Python object — DuckDB's columnar engine reads only required columns. Stratification queries run in under 2 seconds on a laptop.

**Pool-level projection**: The engine aggregates all loans into six parameters (balance, WAC, WAM, CDR, CPR, loss severity). This is standard for ABS cash flow modeling per Moody's Consumer Loan ABS Methodology §6. Loan-level simulation would be impractical for interactive use.

**Vintage selection**: Base assumptions use 2012–2016 completed vintages only. Window validated using Population Stability Index (PSI) — a regime break was detected at the 2011→2012 transition (tightened underwriting post-crisis). All 2012–2016 consecutive vintage-pair PSI values are below 0.10 (stable population).

**Scenario conventions**: Stress (2× CDR, 0.5× CPR) and upside (0.5× CDR, 1.5× CPR) use documented industry multipliers applied consistently across all parameters. Empirical calibration from 2007–2009 recession vintages was not feasible (n=6,529, selection bias toward highest-quality borrowers).
