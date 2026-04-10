# Loan Portfolio Analysis API

REST interface for the Aravalli Capital cash flow engine. Exposes the same
portfolio analysis and scenario modeling that powers the Streamlit dashboard
as a programmable API, allowing external systems to call projection, IRR,
price-solving, and scenario comparison without running the UI.

---

## Setup

**Install dependencies:**
```bash
pip install fastapi uvicorn slowapi
```

**Run the server:**
```bash
uvicorn interface.api:app --reload
```

The API starts on `http://localhost:8000`.

**Interactive docs** (requires server running):
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Authentication

All endpoints except `/health` require an API key passed in the `X-API-Key` request header.

**Default development key:** `dev-key-aravalli`

**Configuring keys in production:**
```bash
export API_KEYS="your-key-1,your-key-2"
uvicorn interface.api:app
```

**Example:**
```bash
curl -H "X-API-Key: dev-key-aravalli" http://localhost:8000/defaults
```

Requests without a valid key return `401 Unauthorized`.

---

## Rate Limiting

- `/pool`: 20 requests per minute (data loading is expensive)
- All other endpoints: 100 requests per minute

Rate limit is applied per API key. Exceeding the limit returns `429 Too Many Requests`.

---

## Endpoints

### `GET /health`
Health check. No authentication required.

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

---

### `GET /defaults`
Returns the default scenario assumptions derived from Part 1 historical analysis
(loan-count credibility-weighted averages across completed vintages 2012–2016).

```bash
curl -H "X-API-Key: dev-key-aravalli" http://localhost:8000/defaults
```

**Response:**
```json
{
  "base_cdr": 0.1755,
  "base_cpr": 0.493,
  "base_loss_severity": 0.9176,
  "stress_cdr": 0.351,
  "stress_cpr": 0.2465,
  "upside_cdr": 0.08775,
  "upside_cpr": 0.7395,
  "description": "..."
}
```

---

### `POST /pool`
Load and summarize a loan pool for a given vintage range. Queries the parquet
file, applies standard data cleaning, and returns pool-level aggregates ready
to pass directly into `/scenarios`, `/irr`, or `/solve-price`.

**This is the starting point for a complete API workflow.**

**Request:**
```json
{
  "vintage_year_start": 2014,
  "vintage_year_end": 2016
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `vintage_year_start` | int | 2007 | First origination year (inclusive) |
| `vintage_year_end` | int | 2018 | Last origination year (inclusive) |
| `data_path` | str | `accepted_2007_to_2018Q4.parquet` | Path to parquet file on server |

**Response:**
```json
{
  "vintage_year_start": 2014,
  "vintage_year_end": 2016,
  "loan_count": 1090929,
  "balance": 1086177772.10,
  "wac": 0.146948,
  "wam": 25,
  "cdr": 0.1755,
  "cpr": 0.493,
  "loss_severity": 0.9176
}
```

---

### `POST /scenarios`
Run base / stress / upside scenario comparison. Returns IRR and bid price at
each target IRR for all three scenarios.

**Request:**
```json
{
  "balance": 1086177772.10,
  "wac": 0.146948,
  "wam": 25,
  "purchase_price": 0.85,
  "target_irrs": [0.10, 0.12, 0.15]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `balance` | float | Yes | Total UPB in dollars |
| `wac` | float | Yes | Weighted average coupon (decimal) |
| `wam` | int | Yes | Weighted average maturity (months) |
| `purchase_price` | float | Yes | Price as fraction of UPB (e.g. 0.85) |
| `target_irrs` | list[float] | No | IRR targets for price solving (default: [0.10, 0.12, 0.15]) |
| `base` | object | No | Override base scenario: `{cdr, cpr, loss_severity}` |
| `stress` | object | No | Override stress scenario: `{cdr, cpr, loss_severity}` |
| `upside` | object | No | Override upside scenario: `{cdr, cpr, loss_severity}` |

**Response:**
```json
{
  "purchase_price": 0.85,
  "scenarios": [
    {
      "scenario": "Base",
      "description": "Historical observed (avg 2012-2016 completed vintages)...",
      "cdr": 0.1755,
      "cpr": 0.493,
      "loss_severity": 0.9176,
      "irr": -0.0125,
      "prices": {"10pct": 0.7866, "12pct": 0.7761, "15pct": 0.7609}
    },
    ...
  ]
}
```

---

### `POST /irr`
Compute IRR for a pool at a given purchase price.

IRR is annualized as nominal APR (monthly IRR × 12), consistent with the
Lending Club `int_rate` convention.

**Request:**
```json
{
  "balance": 1086177772.10,
  "wac": 0.146948,
  "wam": 25,
  "cdr": 0.1755,
  "cpr": 0.493,
  "loss_severity": 0.9176,
  "purchase_price": 0.85
}
```

**Response:**
```json
{
  "irr": -0.012503,
  "purchase_price": 0.85,
  "balance": 1086177772.1,
  "wac": 0.146948,
  "wam": 25
}
```

---

### `POST /solve-price`
Solve for the purchase price that achieves a target IRR.

Uses bisection between 1% and 200% of UPB. Returns `422` if the target IRR
is not achievable within the search range.

**Request:**
```json
{
  "balance": 1086177772.10,
  "wac": 0.146948,
  "wam": 25,
  "cdr": 0.1755,
  "cpr": 0.493,
  "loss_severity": 0.9176,
  "target_irr": 0.12
}
```

**Response:**
```json
{
  "price": 0.776131,
  "target_irr": 0.12,
  "achieved_irr": 0.12
}
```

---

### `POST /project`
Project month-by-month cash flows for a loan pool.

Returns arrays of length `wam` for interest, principal, prepayments, defaults,
losses, and net cash flow.

**Request:**
```json
{
  "balance": 1086177772.10,
  "wac": 0.146948,
  "wam": 25,
  "cdr": 0.1755,
  "cpr": 0.493,
  "loss_severity": 0.9176
}
```

**Response:**
```json
{
  "months": [1, 2, 3, "..."],
  "interest": [12368487.0, 11105365.0, "..."],
  "principal": [34776954.0, 32734875.0, "..."],
  "prepayments": [58820428.0, 52813438.0, "..."],
  "defaults": [18887718.0, 16959618.0, "..."],
  "losses": [17330789.0, 15564095.0, "..."],
  "net_cf": [90061555.0, 82373579.0, "..."]
}
```

---

## Complete Workflow Example

```python
import requests

API_URL = "http://localhost:8000"
HEADERS = {"X-API-Key": "dev-key-aravalli"}

# 1. Load pool parameters for 2014-2016 vintages
pool = requests.post(f"{API_URL}/pool", headers=HEADERS, json={
    "vintage_year_start": 2014,
    "vintage_year_end": 2016,
}).json()

# 2. Run scenario comparison at 85 cents on the dollar
scenarios = requests.post(f"{API_URL}/scenarios", headers=HEADERS, json={
    "balance":        pool["balance"],
    "wac":            pool["wac"],
    "wam":            pool["wam"],
    "purchase_price": 0.85,
}).json()

for s in scenarios["scenarios"]:
    print(f"{s['scenario']}: IRR={s['irr']:.2%}, price@12%={s['prices']['12pct']}")

# 3. Find the bid price to achieve 12% IRR under base assumptions
result = requests.post(f"{API_URL}/solve-price", headers=HEADERS, json={
    "balance":       pool["balance"],
    "wac":           pool["wac"],
    "wam":           pool["wam"],
    "cdr":           pool["cdr"],
    "cpr":           pool["cpr"],
    "loss_severity": pool["loss_severity"],
    "target_irr":    0.12,
}).json()

print(f"Bid {result['price']:.4f} ({result['price']*100:.1f}¢) for 12% IRR")
```

See `examples/api_example.py` for the full annotated version.

---

## Error Reference

| Code | Meaning |
|------|---------|
| `401` | Missing or invalid API key |
| `404` | No loans found for the specified vintage range |
| `422` | Invalid request parameters or target IRR not achievable |
| `429` | Rate limit exceeded |
| `500` | Server error (e.g. data file not found) |
