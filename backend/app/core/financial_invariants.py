"""
KINDpos Financial Invariants

Canonical accounting identities for a day of sales, tender, tips, and
reconciliation. Import and call these checks from aggregation paths so
drift is surfaced the moment it appears, not two weeks later on a
printed report.

Every function comes in two forms:
  - `check_*`   returns an InvariantResult (no exception)
  - `assert_*`  raises InvariantViolation when the check fails

An InvariantResult is truthy when `ok is True`. A non-zero `diff`
captures the signed delta against the expected value so callers can
log it (see `reconciliation_diff` in the close-day summary).

Canonical identities (from SALES_CALC_AUDIT.md):
  - P&L:            Net = Gross − Voids − Discounts − Refunds
  - Tender:         Cash + Card = Net + Tax Collected
  - Tips:           Tips Collected = Card Tips + Cash Tips
  - Cash Expected:  Cash Expected = Cash Sales − Card Tips
  - 2dp gate:       every monetary value rounds to exactly 2 decimal places
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from app.core.money import money_round

_logger = logging.getLogger("kindpos.financial_invariants")

# Default tolerance: a single cent. All checks allow drift within this
# window so ROUND_HALF_UP differences at the aggregation boundary don't
# trip the gate. Callers can tighten to 0 when validating a projection
# that should already be at 2dp.
DEFAULT_TOLERANCE = 0.01


class InvariantViolation(AssertionError):
    """Raised when an `assert_*` invariant fails."""

    def __init__(self, name: str, message: str, diff: float):
        super().__init__(f"{name}: {message} (diff={diff:+.4f})")
        self.name = name
        self.diff = diff


@dataclass(frozen=True)
class InvariantResult:
    name: str
    ok: bool
    diff: float
    message: str

    def __bool__(self) -> bool:  # truthy shorthand in if-statements
        return self.ok


# ── helpers ─────────────────────────────────────────────────────────────────

def _to_float(value: Any) -> float:
    """Safely coerce a number-like value (Decimal, int, float, str) to float."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _round(value: Any) -> float:
    return money_round(_to_float(value))


def _is_2dp(value: Any) -> bool:
    """True when the value is already rounded to exactly 2 decimal places.

    Uses the Decimal quantum so 0.1 + 0.2 (= 0.30000000000000004) is
    caught as not-2dp even though it visually looks fine.
    """
    try:
        d = Decimal(str(value))
    except Exception:
        return False
    if not d.is_finite():
        return False
    # Scale to cents; exact if the quantum fits.
    cents = d * 100
    return cents == cents.to_integral_value()


# ── core identities ─────────────────────────────────────────────────────────

def _signed_diff(observed: float, expected: float) -> float:
    """Compute observed − expected in Decimal space, quantized to the cent.

    Subtracting two floats that each round cleanly to 2dp can still
    yield values like 0.010000000000005116 in IEEE 754. Routing the
    subtraction through Decimal(str(...)) keeps the reported diff
    honest and keeps the tolerance check from spuriously tripping.
    """
    d = Decimal(str(observed)) - Decimal(str(expected))
    return float(d.quantize(Decimal("0.01")))


def _diff_ok(diff: float, tolerance: float) -> bool:
    """True when |diff| <= tolerance, compared in Decimal space."""
    return abs(Decimal(str(diff))) <= Decimal(str(tolerance))


def check_pnl_identity(
    gross: float,
    voids: float,
    discounts: float,
    refunds: float,
    net: float,
    tolerance: float = DEFAULT_TOLERANCE,
) -> InvariantResult:
    """Net = Gross − Voids − Discounts − Refunds.

    Gross is the store-wide sum of all order subtotals including voided
    orders (see the void-double-count fix in SALES_CALC_AUDIT.md).
    Every argument must be in the same sign convention: positive numbers
    for deductions. Net is the observed value the aggregator emits.
    """
    expected = _round(gross - voids - discounts - refunds)
    observed = _round(net)
    diff = _signed_diff(observed, expected)
    ok = _diff_ok(diff, tolerance)
    msg = (
        f"expected Net={expected:.2f} (Gross {_round(gross):.2f} − "
        f"Voids {_round(voids):.2f} − Discounts {_round(discounts):.2f} − "
        f"Refunds {_round(refunds):.2f}); observed Net={observed:.2f}"
    )
    return InvariantResult("pnl_identity", ok, diff, msg)


def assert_pnl_identity(*args, **kwargs) -> None:
    r = check_pnl_identity(*args, **kwargs)
    if not r.ok:
        raise InvariantViolation(r.name, r.message, r.diff)


def check_tender_reconciliation(
    cash_total: float,
    card_total: float,
    net_sales: float,
    tax_collected: float,
    tolerance: float = DEFAULT_TOLERANCE,
) -> InvariantResult:
    """Cash Sales + Card Sales = Net Sales + Tax Collected.

    Both `cash_total` and `card_total` are sums of confirmed `p.amount`
    values (sale amount only — tips are tracked separately). This
    identity holds regardless of voids/discounts because voided orders
    carry no confirmed payments.
    """
    expected = _round(net_sales + tax_collected)
    observed = _round(cash_total + card_total)
    diff = _signed_diff(observed, expected)
    ok = _diff_ok(diff, tolerance)
    msg = (
        f"expected Cash+Card={expected:.2f} (Net {_round(net_sales):.2f} + "
        f"Tax {_round(tax_collected):.2f}); observed {observed:.2f} "
        f"(Cash {_round(cash_total):.2f} + Card {_round(card_total):.2f})"
    )
    return InvariantResult("tender_reconciliation", ok, diff, msg)


def assert_tender_reconciliation(*args, **kwargs) -> None:
    r = check_tender_reconciliation(*args, **kwargs)
    if not r.ok:
        raise InvariantViolation(r.name, r.message, r.diff)


def check_tips_partition(
    total_tips: float,
    card_tips: float,
    cash_tips: float,
    tolerance: float = DEFAULT_TOLERANCE,
) -> InvariantResult:
    """Tips Collected = Card Tips + Cash Tips (partition by tender)."""
    expected = _round(card_tips + cash_tips)
    observed = _round(total_tips)
    diff = _signed_diff(observed, expected)
    ok = _diff_ok(diff, tolerance)
    msg = (
        f"expected Tips={expected:.2f} (Card {_round(card_tips):.2f} + "
        f"Cash {_round(cash_tips):.2f}); observed {observed:.2f}"
    )
    return InvariantResult("tips_partition", ok, diff, msg)


def assert_tips_partition(*args, **kwargs) -> None:
    r = check_tips_partition(*args, **kwargs)
    if not r.ok:
        raise InvariantViolation(r.name, r.message, r.diff)


def check_cash_expected(
    cash_sales: float,
    card_tips: float,
    cash_expected: float,
    tolerance: float = DEFAULT_TOLERANCE,
) -> InvariantResult:
    """Cash Expected = Cash Sales − Card Tips.

    The drawer holds cash sales; card tips will be paid out to servers
    from that cash, so the manager should expect to count that delta
    at close.
    """
    expected = _round(cash_sales - card_tips)
    observed = _round(cash_expected)
    diff = _signed_diff(observed, expected)
    ok = _diff_ok(diff, tolerance)
    msg = (
        f"expected Cash Expected={expected:.2f} (Cash Sales "
        f"{_round(cash_sales):.2f} − Card Tips {_round(card_tips):.2f}); "
        f"observed {observed:.2f}"
    )
    return InvariantResult("cash_expected", ok, diff, msg)


def assert_cash_expected(*args, **kwargs) -> None:
    r = check_cash_expected(*args, **kwargs)
    if not r.ok:
        raise InvariantViolation(r.name, r.message, r.diff)


def check_over_short(
    cash_expected: float,
    actual_cash_counted: float,
    over_short: float,
    tolerance: float = DEFAULT_TOLERANCE,
) -> InvariantResult:
    """Over/Short = Actual Cash Counted − Cash Expected."""
    expected = _round(actual_cash_counted - cash_expected)
    observed = _round(over_short)
    diff = _signed_diff(observed, expected)
    ok = _diff_ok(diff, tolerance)
    msg = (
        f"expected Over/Short={expected:+.2f} (Counted "
        f"{_round(actual_cash_counted):.2f} − Expected "
        f"{_round(cash_expected):.2f}); observed {observed:+.2f}"
    )
    return InvariantResult("over_short", ok, diff, msg)


def assert_over_short(*args, **kwargs) -> None:
    r = check_over_short(*args, **kwargs)
    if not r.ok:
        raise InvariantViolation(r.name, r.message, r.diff)


def check_batch_settlement(
    card_sales: float,
    card_tips: float,
    settlement: float,
    tolerance: float = DEFAULT_TOLERANCE,
) -> InvariantResult:
    """Batch Settlement = Card Sales + Card Tips (what the processor settles)."""
    expected = _round(card_sales + card_tips)
    observed = _round(settlement)
    diff = _signed_diff(observed, expected)
    ok = _diff_ok(diff, tolerance)
    msg = (
        f"expected Settlement={expected:.2f} (Card Sales "
        f"{_round(card_sales):.2f} + Card Tips {_round(card_tips):.2f}); "
        f"observed {observed:.2f}"
    )
    return InvariantResult("batch_settlement", ok, diff, msg)


def assert_batch_settlement(*args, **kwargs) -> None:
    r = check_batch_settlement(*args, **kwargs)
    if not r.ok:
        raise InvariantViolation(r.name, r.message, r.diff)


# ── 2dp gate ────────────────────────────────────────────────────────────────

def check_all_2dp(
    values: Mapping[str, Any] | Iterable[tuple[str, Any]],
) -> InvariantResult:
    """Every named monetary value must be rounded to exactly 2 decimal places.

    Accepts either a dict {name: value} or any iterable of (name, value)
    pairs so callers can scope the check to just the money fields of a
    larger payload (skipping counts, order_ids, timestamps, etc.).
    """
    if isinstance(values, Mapping):
        items = list(values.items())
    else:
        items = list(values)

    bad: list[str] = []
    for name, raw in items:
        if raw is None:
            continue
        if not _is_2dp(raw):
            bad.append(f"{name}={raw!r}")

    ok = not bad
    msg = "all monetary fields at 2dp" if ok else "not 2dp: " + ", ".join(bad)
    diff = 0.0 if ok else float(len(bad))  # not a money delta; count of offenders
    return InvariantResult("all_2dp", ok, diff, msg)


def assert_all_2dp(values) -> None:
    r = check_all_2dp(values)
    if not r.ok:
        raise InvariantViolation(r.name, r.message, r.diff)


# ── composite: run every day-close invariant at once ────────────────────────

def check_day_close(
    *,
    gross_sales: float,
    void_total: float,
    discount_total: float,
    refund_total: float,
    net_sales: float,
    tax_collected: float,
    cash_total: float,
    card_total: float,
    total_tips: float,
    card_tips: float,
    cash_tips: float,
    cash_expected: Optional[float] = None,
    actual_cash_counted: Optional[float] = None,
    over_short: Optional[float] = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[InvariantResult]:
    """Run every canonical identity relevant to a day-close payload.

    Returns one InvariantResult per check. Callers decide whether to
    log, warn, or raise — `assert_day_close` wraps this with raise-on-fail.
    """
    results: list[InvariantResult] = [
        check_pnl_identity(
            gross_sales, void_total, discount_total, refund_total, net_sales,
            tolerance=tolerance,
        ),
        check_tender_reconciliation(
            cash_total, card_total, net_sales, tax_collected,
            tolerance=tolerance,
        ),
        check_tips_partition(
            total_tips, card_tips, cash_tips, tolerance=tolerance,
        ),
    ]
    if cash_expected is not None:
        results.append(check_cash_expected(
            cash_total, card_tips, cash_expected, tolerance=tolerance,
        ))
    if over_short is not None and actual_cash_counted is not None and cash_expected is not None:
        results.append(check_over_short(
            cash_expected, actual_cash_counted, over_short, tolerance=tolerance,
        ))
    return results


def assert_day_close(**kwargs) -> None:
    """Raise InvariantViolation on the first failing check."""
    for r in check_day_close(**kwargs):
        if not r.ok:
            raise InvariantViolation(r.name, r.message, r.diff)


# ── gate: the runtime entry point for aggregators ──────────────────────────

def gate(
    results: Iterable[InvariantResult],
    *,
    context: str = "",
    strict: Optional[bool] = None,
) -> list[InvariantResult]:
    """Consume a batch of check results: always log failures, optionally raise.

    Aggregation paths (get_day_summary, close_batch, close_day,
    _aggregate_orders, print context builders) call this after
    computing totals so drift surfaces immediately.

    `strict` defaults to `settings.strict_invariants`. pytest flips that
    to True via conftest so tests fail loudly on any regression; in
    production the default False logs a warning and lets the caller
    decide what to do with the returned result list (e.g. attach a
    `reconciliation_diff` to the response).
    """
    results = list(results)

    if strict is None:
        try:
            from app.config import settings
            strict = bool(settings.strict_invariants)
        except Exception:
            strict = False

    failures = [r for r in results if not r.ok]
    if failures:
        prefix = f"[{context}] " if context else ""
        for r in failures:
            _logger.warning("%s%s failed: %s", prefix, r.name, r.message)
        if strict:
            first = failures[0]
            raise InvariantViolation(first.name, first.message, first.diff)

    return results


def max_abs_diff(results: Iterable[InvariantResult]) -> float:
    """Largest absolute diff across a batch of results (for reconciliation_diff)."""
    best = 0.0
    for r in results:
        v = abs(r.diff)
        if v > best:
            best = v
    return best
