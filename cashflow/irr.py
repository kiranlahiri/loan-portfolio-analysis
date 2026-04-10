"""
cashflow/irr.py
---------------
IRR calculation and price solver.

Depends only on cashflow/engine.py — no data layer, no pandas.

IRR: uses numpy_financial.irr() (Newton-Raphson internally).
Price solver: bisection on IRR — guaranteed to converge since
IRR is monotonically decreasing in purchase price.
"""

import numpy as np
import numpy_financial as npf

from cashflow.engine import project


def compute_irr(
    balance: float,
    wac: float,
    wam: int,
    cdr: float,
    cpr: float,
    loss_severity: float,
    purchase_price: float,
    timing_curve: np.ndarray | None = None,
) -> float:
    """
    Compute the IRR of a pool investment at a given purchase price.

    The cash flow stream is:
      t=0  : -purchase_price × balance  (upfront investment)
      t=1..wam : net_cf[t]              (monthly receipts)

    Parameters
    ----------
    balance : float
        Total outstanding principal (UPB).
    wac : float
        Weighted average coupon as a decimal.
    wam : int
        Weighted average maturity in months.
    cdr : float
        Annual default rate assumption as a decimal.
    cpr : float
        Annual prepayment rate assumption as a decimal.
    loss_severity : float
        Fraction of defaulted balance permanently lost.
    purchase_price : float
        Price paid as a fraction of UPB (e.g. 0.85 for 85 cents on the dollar).
    timing_curve : np.ndarray or None
        Optional default timing curve (see engine.project).

    Returns
    -------
    float
        Annualized IRR. Returns np.nan if IRR cannot be computed
        (e.g. all cash flows are negative).
    """
    result = project(balance, wac, wam, cdr, cpr, loss_severity, timing_curve)
    net_cf = result["net_cf"]

    # Prepend the upfront investment as a negative cash flow at t=0
    cash_flows = np.concatenate([[-purchase_price * balance], net_cf])

    monthly_irr = npf.irr(cash_flows)

    if np.isnan(monthly_irr):
        return np.nan

    # Annualize as nominal APR (monthly × 12), consistent with how WAC and
    # int_rate are quoted on Lending Club loans. This ensures IRR = WAC when
    # buying at par with 0% CDR/CPR — the fundamental known-answer test.
    return monthly_irr * 12


def solve_price(
    balance: float,
    wac: float,
    wam: int,
    cdr: float,
    cpr: float,
    loss_severity: float,
    target_irr: float,
    timing_curve: np.ndarray | None = None,
    low: float = 0.01,
    high: float = 2.00,
    tolerance: float = 1e-6,
    max_iter: int = 100,
) -> float:
    """
    Find the purchase price (as fraction of UPB) that achieves a target IRR.

    Uses bisection — IRR is monotonically decreasing in price, so bisection
    is guaranteed to converge to a unique solution within [low, high].

    Parameters
    ----------
    balance : float
        Total outstanding principal (UPB).
    wac : float
        Weighted average coupon as a decimal.
    wam : int
        Weighted average maturity in months.
    cdr : float
        Annual default rate assumption as a decimal.
    cpr : float
        Annual prepayment rate assumption as a decimal.
    loss_severity : float
        Fraction of defaulted balance permanently lost.
    target_irr : float
        Target annualized IRR as a decimal (e.g. 0.12 for 12%).
    timing_curve : np.ndarray or None
        Optional default timing curve (see engine.project).
    low : float
        Lower bound on price search (default 1% of UPB).
    high : float
        Upper bound on price search (default 200% of UPB).
    tolerance : float
        Convergence tolerance on price (default 1e-6).
    max_iter : int
        Maximum bisection iterations (default 100).

    Returns
    -------
    float
        Purchase price as a fraction of UPB that achieves target_irr.

    Raises
    ------
    ValueError
        If target IRR is not achievable within [low, high].
    """
    def irr_at_price(p):
        return compute_irr(balance, wac, wam, cdr, cpr, loss_severity, p, timing_curve)

    irr_low  = irr_at_price(low)
    irr_high = irr_at_price(high)

    # IRR decreases as price increases, so:
    #   irr_low  should be > target_irr  (cheap price → high return)
    #   irr_high should be < target_irr  (expensive price → low return)
    if irr_low < target_irr:
        raise ValueError(
            f"Target IRR {target_irr:.2%} not achievable even at price={low:.2f}. "
            f"Max achievable IRR: {irr_low:.2%}"
        )
    if irr_high > target_irr:
        raise ValueError(
            f"Target IRR {target_irr:.2%} requires price above {high:.2f}. "
            f"IRR at price={high:.2f}: {irr_high:.2%}"
        )

    for _ in range(max_iter):
        mid = (low + high) / 2
        irr_mid = irr_at_price(mid)

        if np.isnan(irr_mid):
            high = mid
            continue

        if irr_mid > target_irr:
            low = mid   # price too low → IRR too high → raise price
        else:
            high = mid  # price too high → IRR too low → lower price

        if (high - low) < tolerance:
            break

    return (low + high) / 2
