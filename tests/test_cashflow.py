"""
tests/test_cashflow.py
----------------------
Tests for the cash flow engine, IRR solver, and price solver.

The key design principle: tests use *known-answer cases* derived by hand,
so any failure indicates a real bug in the math — not just a regression.

Known-answer test methodology:
  A single loan with known parameters has a deterministic payment schedule
  computable by the standard annuity formula. The engine must reproduce
  these values exactly (within floating-point tolerance).

Run with:
  pytest tests/test_cashflow.py -v
"""

import numpy as np
import pytest

from cashflow.engine import project, _scheduled_payment, _monthly_rate
from cashflow.irr import compute_irr, solve_price
from cashflow.pool import from_dict, PoolSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def annuity_payment(principal: float, annual_rate: float, months: int) -> float:
    """Standard level-payment annuity formula — ground truth for tests."""
    r = annual_rate / 12
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** (-months))


# ---------------------------------------------------------------------------
# engine.py tests
# ---------------------------------------------------------------------------

class TestScheduledPayment:
    def test_standard_loan(self):
        """Monthly payment on $10k, 12% WAC, 12-month term."""
        payment = _scheduled_payment(10_000, 0.12 / 12, 12)
        expected = annuity_payment(10_000, 0.12, 12)
        assert abs(payment - expected) < 0.01

    def test_zero_balance(self):
        assert _scheduled_payment(0, 0.01, 12) == 0.0

    def test_zero_periods(self):
        assert _scheduled_payment(10_000, 0.01, 0) == 0.0

    def test_zero_rate(self):
        """Zero-rate loan: payment = balance / periods."""
        payment = _scheduled_payment(12_000, 0.0, 12)
        assert abs(payment - 1_000.0) < 0.01


class TestMonthlyRate:
    def test_smm_convention(self):
        """
        SMM formula: monthly = 1 - (1 - annual)^(1/12)
        Inverse: (1 - monthly)^12 = 1 - annual → annual = 1 - (1 - monthly)^12
        At CDR=50%: MDR = 1 - 0.5^(1/12) ≈ 5.6% per month
        """
        annual = 0.50
        monthly = _monthly_rate(annual)
        recovered = 1 - (1 - monthly) ** 12
        assert abs(recovered - annual) < 1e-10

    def test_zero_rate(self):
        assert _monthly_rate(0.0) == 0.0


class TestProjectEngine:
    def test_zero_cdr_zero_cpr_total_cash(self):
        """
        With 0% CDR and 0% CPR, total cash flows = principal + interest
        on a standard amortizing loan. The sum of all payments equals
        monthly_payment × wam.
        """
        balance = 10_000.0
        wac     = 0.12
        wam     = 12
        result  = project(balance, wac, wam, cdr=0.0, cpr=0.0, loss_severity=0.0)

        expected_payment = annuity_payment(balance, wac, wam)
        expected_total   = expected_payment * wam

        actual_total = (result["interest"] + result["principal"]).sum()
        assert abs(actual_total - expected_total) < 1.0, (
            f"Expected total cash flows {expected_total:.2f}, got {actual_total:.2f}"
        )

    def test_zero_cdr_zero_cpr_balance_runs_to_zero(self):
        """With no defaults or prepayments, the pool fully amortizes."""
        result = project(10_000, 0.12, 12, cdr=0.0, cpr=0.0, loss_severity=0.0)
        # Final balance should be near zero
        final_balance = result["balance_sod"][-1] - result["principal"][-1]
        assert abs(final_balance) < 1.0, f"Residual balance: {final_balance:.4f}"

    def test_zero_cdr_zero_cpr_first_month(self):
        """
        First month: interest = balance × monthly_rate,
        principal = payment - interest.
        """
        balance = 10_000.0
        wac     = 0.12
        wam     = 12
        result  = project(balance, wac, wam, cdr=0.0, cpr=0.0, loss_severity=0.0)

        expected_interest  = balance * (wac / 12)
        expected_payment   = annuity_payment(balance, wac, wam)
        expected_principal = expected_payment - expected_interest

        assert abs(result["interest"][0]  - expected_interest)  < 0.01
        assert abs(result["principal"][0] - expected_principal) < 0.01

    def test_full_default_month_one(self):
        """
        CDR = 100% in month 1 via timing_curve: entire balance defaults.
        Net cash flow = -(balance × loss_severity).
        """
        balance      = 10_000.0
        loss_severity = 0.9176
        # All defaults in month 1, none after
        timing_curve = np.zeros(12)
        timing_curve[0] = 1.0

        result = project(
            balance, wac=0.12, wam=12,
            cdr=1.0, cpr=0.0,
            loss_severity=loss_severity,
            timing_curve=timing_curve,
        )

        expected_loss = balance * loss_severity
        assert abs(result["losses"][0] - expected_loss) < 1.0
        # After month 1, pool is exhausted — all subsequent CFs should be 0
        assert result["net_cf"][1:].sum() == pytest.approx(0.0, abs=1.0)

    def test_full_prepayment_month_one(self):
        """
        CPR = 100% in month 1: entire remaining balance prepays.
        No defaults, no losses — all principal returned immediately.
        """
        balance = 10_000.0
        result  = project(
            balance, wac=0.12, wam=12,
            cdr=0.0, cpr=1.0,
            loss_severity=0.9176,
        )
        # All prepayments in month 1
        assert abs(result["prepayments"][0] - balance) < 1.0
        assert result["losses"].sum() == pytest.approx(0.0, abs=0.01)

    def test_output_arrays_have_correct_length(self):
        """Output arrays must have length == wam."""
        wam    = 36
        result = project(100_000, 0.13, wam, 0.17, 0.49, 0.9176)
        for key in ["interest", "principal", "prepayments", "defaults",
                    "losses", "net_cf", "balance_sod"]:
            assert len(result[key]) == wam, f"{key} has wrong length"

    def test_timing_curve_wrong_length_raises(self):
        with pytest.raises(ValueError, match="timing_curve length"):
            project(10_000, 0.12, 12, 0.17, 0.0, 0.9176,
                    timing_curve=np.ones(6) / 6)

    def test_timing_curve_doesnt_sum_to_one_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            bad_curve = np.ones(12) * 0.05  # sums to 0.6, not 1.0
            project(10_000, 0.12, 12, 0.17, 0.0, 0.9176,
                    timing_curve=bad_curve)

    def test_net_cf_equals_components(self):
        """net_cf must equal interest + principal + prepayments - losses."""
        result = project(100_000, 0.13, 36, 0.17, 0.49, 0.9176)
        expected_net = (
            result["interest"] +
            result["principal"] +
            result["prepayments"] -
            result["losses"]
        )
        np.testing.assert_allclose(result["net_cf"], expected_net, atol=1e-6)


# ---------------------------------------------------------------------------
# irr.py tests
# ---------------------------------------------------------------------------

class TestComputeIRR:
    def test_zero_default_zero_prepay_par_price(self):
        """
        Key known-answer test: with 0% CDR, 0% CPR, purchased at par (100%),
        IRR must equal WAC exactly.

        Rationale: the investor pays exactly the present value of the cash flows
        discounted at WAC, so the return equals WAC by construction.
        """
        balance  = 10_000.0
        wac      = 0.12
        wam      = 12

        irr = compute_irr(
            balance, wac, wam,
            cdr=0.0, cpr=0.0,
            loss_severity=0.0,
            purchase_price=1.0,
        )
        assert abs(irr - wac) < 0.001, (
            f"Expected IRR ≈ WAC = {wac:.2%}, got {irr:.2%}"
        )

    def test_discount_price_yields_higher_irr(self):
        """Buying below par (e.g. 90 cents) should yield higher IRR than WAC."""
        irr = compute_irr(10_000, 0.12, 12, 0.0, 0.0, 0.0, purchase_price=0.90)
        assert irr > 0.12, f"Expected IRR > 12%, got {irr:.2%}"

    def test_premium_price_yields_lower_irr(self):
        """Buying above par (e.g. 110 cents) should yield lower IRR than WAC."""
        irr = compute_irr(10_000, 0.12, 12, 0.0, 0.0, 0.0, purchase_price=1.10)
        assert irr < 0.12, f"Expected IRR < 12%, got {irr:.2%}"

    def test_high_cdr_reduces_irr(self):
        """Higher CDR (more defaults, more losses) reduces IRR."""
        irr_base   = compute_irr(100_000, 0.13, 36, 0.05, 0.49, 0.9176, 0.85)
        irr_stress = compute_irr(100_000, 0.13, 36, 0.34, 0.49, 0.9176, 0.85)
        assert irr_stress < irr_base, "Higher CDR should reduce IRR"

    def test_irr_on_larger_pool_same_as_small(self):
        """IRR is scale-invariant — $1M pool and $1B pool same WAC/WAM/CDR/CPR
        purchased at same price fraction should yield same IRR."""
        irr_small = compute_irr(1_000_000,     0.13, 36, 0.17, 0.49, 0.9176, 0.85)
        irr_large = compute_irr(1_000_000_000, 0.13, 36, 0.17, 0.49, 0.9176, 0.85)
        assert abs(irr_small - irr_large) < 0.0001, (
            f"IRR should be scale-invariant: {irr_small:.4%} vs {irr_large:.4%}"
        )


class TestSolvePrice:
    def test_solve_price_roundtrip(self):
        """
        solve_price should find a price such that compute_irr(price) ≈ target.
        This is the fundamental roundtrip test.
        """
        balance      = 100_000.0
        wac          = 0.13
        wam          = 36
        cdr          = 0.17
        cpr          = 0.49
        loss_severity = 0.9176
        target_irr   = 0.10

        price = solve_price(balance, wac, wam, cdr, cpr, loss_severity, target_irr)
        actual_irr = compute_irr(balance, wac, wam, cdr, cpr, loss_severity, price)

        assert abs(actual_irr - target_irr) < 0.0001, (
            f"Roundtrip failed: target {target_irr:.2%}, got {actual_irr:.2%} "
            f"at price {price:.4f}"
        )

    def test_solve_price_zero_default_par(self):
        """
        With 0% CDR and 0% CPR, price for target IRR = WAC should be ~1.0 (par).
        """
        price = solve_price(
            10_000, wac=0.12, wam=12,
            cdr=0.0, cpr=0.0, loss_severity=0.0,
            target_irr=0.12,
        )
        assert abs(price - 1.0) < 0.001, (
            f"Expected price ≈ 1.0 (par), got {price:.4f}"
        )

    def test_higher_target_irr_requires_lower_price(self):
        """To achieve a higher return, you must pay less."""
        kwargs = dict(balance=100_000, wac=0.13, wam=36,
                      cdr=0.17, cpr=0.49, loss_severity=0.9176)
        price_10 = solve_price(**kwargs, target_irr=0.10)
        price_15 = solve_price(**kwargs, target_irr=0.15)
        assert price_15 < price_10, (
            f"Higher IRR target should require lower price: "
            f"10%→{price_10:.4f}, 15%→{price_15:.4f}"
        )

    def test_unreachable_target_raises(self):
        """
        Target IRR above what's achievable in the search range raises ValueError.

        At price=0.80 with WAC=5%, CDR=0%, CPR=0%, the IRR is slightly above 5%
        (buying below par). A target of 500% (50× WAC) is wildly out of range
        → irr_low < target_irr → ValueError.
        """
        with pytest.raises(ValueError, match="Max achievable IRR"):
            solve_price(
                10_000, wac=0.05, wam=36,
                cdr=0.0, cpr=0.0, loss_severity=0.0,
                target_irr=5.0,      # 500% annual — far above achievable
                low=0.80, high=2.0,  # constrain search to sensible price range
            )


# ---------------------------------------------------------------------------
# pool.py tests
# ---------------------------------------------------------------------------

class TestPoolSnapshot:
    def test_from_dict_basic(self):
        snap = from_dict({
            "balance": 1_000_000,
            "wac": 0.1324,
            "wam": 39,
            "cdr": 0.17,
            "cpr": 0.49,
            "loss_severity": 0.9176,
        })
        assert isinstance(snap, PoolSnapshot)
        assert snap.balance == 1_000_000
        assert snap.wac == 0.1324
        assert snap.wam == 39

    def test_from_dict_missing_key_raises(self):
        with pytest.raises(ValueError, match="Missing required keys"):
            from_dict({"balance": 1_000_000, "wac": 0.13})

    def test_snapshot_feeds_engine(self):
        """PoolSnapshot values can be unpacked directly into project()."""
        snap   = from_dict({
            "balance": 100_000, "wac": 0.13, "wam": 36,
            "cdr": 0.17, "cpr": 0.49, "loss_severity": 0.9176,
        })
        result = project(snap.balance, snap.wac, snap.wam,
                         snap.cdr, snap.cpr, snap.loss_severity)
        assert result["net_cf"].sum() > 0
