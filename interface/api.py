"""
interface/api.py
-----------------
FastAPI REST interface for the Aravalli Capital cash flow engine.

Exposes the cash flow engine as a programmatic API, allowing external
systems to call projection, IRR, price-solving, and scenario comparison
without running the Streamlit UI.

Authentication:
    All endpoints (except /health) require an API key passed in the
    X-API-Key request header. Keys are configured via the API_KEYS
    environment variable (comma-separated). If not set, defaults to a
    single development key: "dev-key-aravalli".

    Example:
        curl -H "X-API-Key: dev-key-aravalli" http://localhost:8000/defaults

Rate limiting:
    100 requests per minute per API key. Exceeding this returns HTTP 429.

CORS:
    Configured to allow requests from any origin. Restrict
    ALLOWED_ORIGINS in production to your specific frontend domains.

Run with:
    uvicorn interface.api:app --reload

Interactive docs available at:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""

import os
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from cashflow.engine import project
from cashflow.irr import compute_irr, solve_price
from cashflow.scenarios import (
    compare_scenarios, build_scenarios,
    BASE_CDR, BASE_CPR, BASE_LOSS_SEVERITY,
)
from cashflow.pool import from_lending_club
from data.ingest import get_loans


# ---------------------------------------------------------------------------
# API key configuration
# ---------------------------------------------------------------------------

_raw_keys = os.environ.get("API_KEYS", "dev-key-aravalli")
VALID_API_KEYS = {k.strip() for k in _raw_keys.split(",") if k.strip()}

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    if api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return api_key


# ---------------------------------------------------------------------------
# Rate limiter — 100 requests/minute per API key
# ---------------------------------------------------------------------------

def _key_func(request: Request) -> str:
    """Use API key as the rate limit identity; fall back to IP."""
    return request.headers.get("X-API-Key") or get_remote_address(request)


limiter = Limiter(key_func=_key_func)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Aravalli Capital — Loan Portfolio Analysis API",
    description=(
        "REST interface for the cash flow projection engine. "
        "All rates are expressed as decimals (e.g. 0.1755 for 17.55%). "
        "IRR is annualized as nominal APR, consistent with the Lending Club int_rate convention.\n\n"
        "**Authentication:** Pass your API key in the `X-API-Key` header.\n\n"
        "**Rate limit:** 100 requests per minute per API key."
    ),
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict to specific domains in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Rate limiting
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):  # noqa: ARG001
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Max 100 requests per minute per API key."},
    )


# ---------------------------------------------------------------------------
# Shared request/response models
# ---------------------------------------------------------------------------

class PoolParams(BaseModel):
    balance: float = Field(..., gt=0, description="Total outstanding principal (UPB) in dollars.")
    wac: float     = Field(..., gt=0, lt=1, description="Weighted average coupon as a decimal (e.g. 0.1324 for 13.24%).")
    wam: int       = Field(..., gt=0, le=360, description="Weighted average maturity in months.")
    cdr: float     = Field(..., ge=0, lt=1, description="Annual cumulative default rate as a decimal.")
    cpr: float     = Field(..., ge=0, lt=1, description="Annual cumulative prepayment rate as a decimal.")
    loss_severity: float = Field(..., ge=0, le=1, description="Fraction of defaulted balance permanently lost.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "balance": 9_456_500_000,
                "wac": 0.1324,
                "wam": 39,
                "cdr": 0.1755,
                "cpr": 0.4930,
                "loss_severity": 0.9176,
            }
        }
    }


class ProjectRequest(PoolParams):
    pass


class ProjectResponse(BaseModel):
    months:      list[int]   = Field(..., description="Month index (1-based).")
    interest:    list[float] = Field(..., description="Monthly interest cash flows.")
    principal:   list[float] = Field(..., description="Monthly scheduled principal cash flows.")
    prepayments: list[float] = Field(..., description="Monthly prepayment cash flows.")
    defaults:    list[float] = Field(..., description="Monthly defaulted balance.")
    losses:      list[float] = Field(..., description="Monthly net losses (defaults × severity).")
    net_cf:      list[float] = Field(..., description="Monthly net cash flows to investor.")
    balance_sod: list[float] = Field(..., description="Pool balance at start of each month.")


class IrrRequest(PoolParams):
    purchase_price: float = Field(..., gt=0, le=2.0,
        description="Price paid as a fraction of UPB (e.g. 0.85 for 85 cents on the dollar).")

    model_config = {
        "json_schema_extra": {
            "example": {
                "balance": 9_456_500_000,
                "wac": 0.1324,
                "wam": 39,
                "cdr": 0.1755,
                "cpr": 0.4930,
                "loss_severity": 0.9176,
                "purchase_price": 0.85,
            }
        }
    }


class IrrResponse(BaseModel):
    irr: float = Field(..., description="Annualized IRR as a decimal (nominal APR convention).")
    purchase_price: float
    balance: float
    wac: float
    wam: int


class SolvePriceRequest(PoolParams):
    target_irr: float = Field(..., gt=0, lt=5.0,
        description="Target IRR as a decimal (e.g. 0.12 for 12%).")

    model_config = {
        "json_schema_extra": {
            "example": {
                "balance": 9_456_500_000,
                "wac": 0.1324,
                "wam": 39,
                "cdr": 0.1755,
                "cpr": 0.4930,
                "loss_severity": 0.9176,
                "target_irr": 0.12,
            }
        }
    }


class SolvePriceResponse(BaseModel):
    price: float       = Field(..., description="Price as a fraction of UPB that achieves the target IRR.")
    target_irr: float
    achieved_irr: float = Field(..., description="Actual IRR at the solved price (should match target within 0.01%).")


class ScenarioOverride(BaseModel):
    cdr:           Optional[float] = Field(None, ge=0, lt=1)
    cpr:           Optional[float] = Field(None, ge=0, lt=1)
    loss_severity: Optional[float] = Field(None, ge=0, le=1)


class ScenariosRequest(BaseModel):
    balance:        float = Field(..., gt=0)
    wac:            float = Field(..., gt=0, lt=1)
    wam:            int   = Field(..., gt=0, le=360)
    purchase_price: float = Field(..., gt=0, le=2.0)
    target_irrs:    list[float] = Field(default=[0.10, 0.12, 0.15],
        description="IRR targets for price solving.")
    base:   Optional[ScenarioOverride] = Field(None, description="Override base scenario parameters.")
    stress: Optional[ScenarioOverride] = Field(None, description="Override stress scenario parameters.")
    upside: Optional[ScenarioOverride] = Field(None, description="Override upside scenario parameters.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "balance": 9_456_500_000,
                "wac": 0.1324,
                "wam": 39,
                "purchase_price": 0.85,
                "target_irrs": [0.10, 0.12, 0.15],
            }
        }
    }


class ScenarioResult(BaseModel):
    scenario:      str
    description:   str
    cdr:           float
    cpr:           float
    loss_severity: float
    irr:           Optional[float]
    prices:        dict[str, Optional[float]] = Field(...,
        description="Price for each target IRR, keyed by IRR percentage (e.g. '10pct').")


class ScenariosResponse(BaseModel):
    purchase_price: float
    scenarios:      list[ScenarioResult]


class DefaultsResponse(BaseModel):
    base_cdr:           float
    base_cpr:           float
    base_loss_severity: float
    stress_cdr:         float
    stress_cpr:         float
    upside_cdr:         float
    upside_cpr:         float
    description:        str


class PoolRequest(BaseModel):
    vintage_year_start: int = Field(2007, ge=2007, le=2018,
        description="First origination year to include (inclusive).")
    vintage_year_end:   int = Field(2018, ge=2007, le=2018,
        description="Last origination year to include (inclusive).")
    data_path: str = Field("accepted_2007_to_2018Q4.parquet",
        description="Path to the parquet file on the server.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "vintage_year_start": 2014,
                "vintage_year_end": 2016,
            }
        }
    }


class PoolResponse(BaseModel):
    vintage_year_start: int
    vintage_year_end:   int
    loan_count:         int
    balance:            float = Field(..., description="Total outstanding principal (UPB) in dollars.")
    wac:                float = Field(..., description="Weighted average coupon as a decimal.")
    wam:                int   = Field(..., description="Weighted average maturity in months.")
    cdr:                float = Field(..., description="Historical CDR (avg completed vintages 2012-2016).")
    cpr:                float = Field(..., description="Historical CPR (avg completed vintages 2012-2016).")
    loss_severity:      float = Field(..., description="Historical loss severity.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health():
    """Health check — returns 200 if the API is running."""
    return {"status": "ok"}


@app.get("/defaults", response_model=DefaultsResponse, tags=["System"])
@limiter.limit("100/minute")
def defaults(request: Request, _key: str = Security(require_api_key)):
    """
    Return the default scenario assumptions derived from Part 1 historical analysis
    (avg completed vintages 2012-2016).
    """
    return DefaultsResponse(
        base_cdr=BASE_CDR,
        base_cpr=BASE_CPR,
        base_loss_severity=BASE_LOSS_SEVERITY,
        stress_cdr=round(BASE_CDR * 2.0, 4),
        stress_cpr=round(BASE_CPR * 0.5, 4),
        upside_cdr=round(BASE_CDR * 0.5, 4),
        upside_cpr=round(BASE_CPR * 1.5, 4),
        description=(
            "Base assumptions are loan-count credibility-weighted averages across "
            "completed vintages 2012-2016. Stress/upside multipliers are documented "
            "industry conventions (2x/0.5x CDR, 0.5x/1.5x CPR). "
            "See scenarios.py module docstring for full calibration rationale."
        ),
    )


@app.post("/pool", response_model=PoolResponse, tags=["Pool"])
@limiter.limit("20/minute")
def pool_endpoint(request: Request, req: PoolRequest, _key: str = Security(require_api_key)):
    """
    Load and summarize a loan pool for a given vintage range.

    Queries the parquet file, applies standard data cleaning, and returns
    pool-level aggregates (WAC, WAM, CDR, CPR, loss severity) ready to
    pass directly into /irr, /solve-price, or /scenarios.

    This is the entry point for a complete API workflow:
        POST /pool       → get pool parameters for a vintage range
        POST /scenarios  → run base/stress/upside scenario comparison
        POST /solve-price → find the bid price for a target IRR

    Rate limited to 20 requests/minute (data loading is expensive).
    """
    if req.vintage_year_start > req.vintage_year_end:
        raise HTTPException(status_code=422, detail="vintage_year_start must be <= vintage_year_end.")

    try:
        df = get_loans(req.data_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load data: {e}")

    df = df[df["issue_date"].dt.year.between(req.vintage_year_start, req.vintage_year_end)]

    if len(df) == 0:
        raise HTTPException(status_code=404, detail="No loans found for the specified vintage range.")

    snap = from_lending_club(df)

    return PoolResponse(
        vintage_year_start=req.vintage_year_start,
        vintage_year_end=req.vintage_year_end,
        loan_count=snap.loan_count,
        balance=round(snap.balance, 2),
        wac=round(snap.wac, 6),
        wam=snap.wam,
        cdr=round(snap.cdr, 6),
        cpr=round(snap.cpr, 6),
        loss_severity=round(snap.loss_severity, 6),
    )


@app.post("/project", response_model=ProjectResponse, tags=["Engine"])
@limiter.limit("100/minute")
def project_cashflows(request: Request, req: ProjectRequest, _key: str = Security(require_api_key)):
    """
    Project monthly cash flows for a loan pool.

    Returns month-by-month arrays for interest, principal, prepayments,
    defaults, losses, and net cash flow to the investor.

    The projection follows Moody's Consumer Loan ABS Methodology:
    - SMM convention for monthly CDR/CPR conversion
    - Front-loaded default timing (uniform distribution by default)
    - Waterfall: defaults → prepayments → scheduled amortization → losses
    """
    cf = project(
        balance=req.balance,
        wac=req.wac,
        wam=req.wam,
        cdr=req.cdr,
        cpr=req.cpr,
        loss_severity=req.loss_severity,
    )
    n = req.wam
    return ProjectResponse(
        months=list(range(1, n + 1)),
        interest=cf["interest"].tolist(),
        principal=cf["principal"].tolist(),
        prepayments=cf["prepayments"].tolist(),
        defaults=cf["defaults"].tolist(),
        losses=cf["losses"].tolist(),
        net_cf=cf["net_cf"].tolist(),
        balance_sod=cf["balance_sod"].tolist(),
    )


@app.post("/irr", response_model=IrrResponse, tags=["Engine"])
@limiter.limit("100/minute")
def compute_irr_endpoint(request: Request, req: IrrRequest, _key: str = Security(require_api_key)):
    """
    Compute IRR for a loan pool at a given purchase price.

    IRR is the discount rate that makes the NPV of projected cash flows
    equal to the purchase price. Annualized as nominal APR (monthly IRR × 12),
    consistent with the Lending Club int_rate convention.
    """
    irr = compute_irr(
        balance=req.balance,
        wac=req.wac,
        wam=req.wam,
        cdr=req.cdr,
        cpr=req.cpr,
        loss_severity=req.loss_severity,
        purchase_price=req.purchase_price,
    )
    if irr is None or (isinstance(irr, float) and np.isnan(irr)):
        raise HTTPException(status_code=422, detail="IRR could not be computed for the given inputs.")

    return IrrResponse(
        irr=round(irr, 6),
        purchase_price=req.purchase_price,
        balance=req.balance,
        wac=req.wac,
        wam=req.wam,
    )


@app.post("/solve-price", response_model=SolvePriceResponse, tags=["Engine"])
@limiter.limit("100/minute")
def solve_price_endpoint(request: Request, req: SolvePriceRequest, _key: str = Security(require_api_key)):
    """
    Solve for the purchase price that achieves a target IRR.

    Uses bisection between 1% and 200% of UPB. Guaranteed to converge
    since IRR is monotonically decreasing in price.

    Returns 422 if the target IRR is not achievable within the search range
    (e.g. target is higher than the pool's WAC with zero defaults).
    """
    try:
        price = solve_price(
            balance=req.balance,
            wac=req.wac,
            wam=req.wam,
            cdr=req.cdr,
            cpr=req.cpr,
            loss_severity=req.loss_severity,
            target_irr=req.target_irr,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    achieved = compute_irr(
        balance=req.balance,
        wac=req.wac,
        wam=req.wam,
        cdr=req.cdr,
        cpr=req.cpr,
        loss_severity=req.loss_severity,
        purchase_price=price,
    )

    return SolvePriceResponse(
        price=round(price, 6),
        target_irr=req.target_irr,
        achieved_irr=round(achieved, 6),
    )


@app.post("/scenarios", response_model=ScenariosResponse, tags=["Scenarios"])
@limiter.limit("100/minute")
def scenarios_endpoint(request: Request, req: ScenariosRequest, _key: str = Security(require_api_key)):
    """
    Run base / stress / upside scenario comparison.

    Returns IRR and price-for-target-IRR for each scenario. Default
    scenario parameters are derived from historical analysis (avg completed
    vintages 2012-2016). All parameters can be overridden individually.

    Stress convention: 2× CDR, 0.5× CPR (recession assumption).
    Upside convention: 0.5× CDR, 1.5× CPR (recovery assumption).
    """
    scenario_list = build_scenarios(
        stress_cdr=req.stress.cdr if req.stress else None,
        stress_cpr=req.stress.cpr if req.stress else None,
        stress_loss_severity=req.stress.loss_severity if req.stress else None,
        upside_cdr=req.upside.cdr if req.upside else None,
        upside_cpr=req.upside.cpr if req.upside else None,
        upside_loss_severity=req.upside.loss_severity if req.upside else None,
        **({"base_cdr": req.base.cdr} if req.base and req.base.cdr else {}),
        **({"base_cpr": req.base.cpr} if req.base and req.base.cpr else {}),
        **({"base_loss_severity": req.base.loss_severity} if req.base and req.base.loss_severity else {}),
    )

    df = compare_scenarios(
        balance=req.balance,
        wac=req.wac,
        wam=req.wam,
        purchase_price=req.purchase_price,
        scenarios=scenario_list,
        target_irrs=tuple(req.target_irrs),
    )

    results = []
    for _, row in df.iterrows():
        prices = {}
        for t in req.target_irrs:
            col = f"price_for_{int(t * 100)}pct_irr"
            v = row.get(col)
            prices[f"{int(t * 100)}pct"] = round(float(v), 6) if v is not None and not np.isnan(v) else None

        results.append(ScenarioResult(
            scenario=row["scenario"],
            description=row["description"],
            cdr=round(row["cdr"], 6),
            cpr=round(row["cpr"], 6),
            loss_severity=round(row["loss_severity"], 6),
            irr=round(float(row["irr"]), 6) if row["irr"] is not None and not np.isnan(row["irr"]) else None,
            prices=prices,
        ))

    return ScenariosResponse(
        purchase_price=req.purchase_price,
        scenarios=results,
    )
