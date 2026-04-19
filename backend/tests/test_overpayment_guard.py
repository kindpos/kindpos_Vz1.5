"""
Regression tests for the $0.40 overpayment drift the runtime gate
caught in production.

Scenario: a frontend sends `amount=$8.40` for an order whose backend
`balance_due` is $8.00 (typical when the frontend's local TAX_RATE
is stale vs. backend's `settings.tax_rate`). Without the guard added
to `process_cash_payment` and `process_sale`, `p.amount` was stored
as $8.40, while aggregation saw net=$8.00 + tax=$0.00 — tripping the
tender_reconciliation invariant.

These tests prove the backend guard clamps the sale at balance_due
and routes the excess into a TIP_ADJUSTED event, so the tender
identity (Cash+Card = Net+Tax) keeps holding even when the frontend
sends an inflated amount.
"""

import os
from pathlib import Path

import pytest
import pytest_asyncio

from app.api.routes.payment_routes import CashPaymentRequest, process_cash_payment
from app.api.routes.reporting import _aggregate_orders
from app.config import settings
from app.core.event_ledger import EventLedger
from app.core.events import item_added, order_created
from app.core.financial_invariants import (
    check_tender_reconciliation,
    check_tips_partition,
)
from app.core.projections import project_order


TEST_DB = Path("./data/test_overpayment_guard.db")
TERMINAL = "terminal_test"


@pytest.fixture(autouse=True)
def _zero_tax_and_discount(monkeypatch):
    """Pin the POS pricing constants for these tests.

    The repo's `conftest.py` seeds KINDPOS_TAX_RATE=0.07 and
    KINDPOS_CASH_DISCOUNT_RATE=0.04, which would mutate the
    balance_due we're trying to compare against. These tests
    specifically exercise the overpayment guard, so we want a
    clean subtotal == balance_due baseline.
    """
    monkeypatch.setattr(settings, "tax_rate", 0.0)
    monkeypatch.setattr(settings, "cash_discount_rate", 0.0)


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


async def _seed_eight_dollar_order(ledger, order_id: str = "o_guard_01"):
    """Ledger: one order with a single $8.00 item, no tax.

    `correlation_id=order_id` is required for `get_events_by_correlation`
    to return these events — the event factories don't set it by default.
    """
    await ledger.append(order_created(
        terminal_id=TERMINAL,
        order_id=order_id,
        order_type="dine_in",
        guest_count=1,
        correlation_id=order_id,
    ))
    await ledger.append(item_added(
        terminal_id=TERMINAL,
        order_id=order_id,
        item_id="i_guard_01",
        menu_item_id="m1",
        name="Item",
        price=8.00,
        quantity=1,
    ))
    return order_id


@pytest.mark.asyncio
async def test_cash_overpayment_clamped_and_tipped(ledger):
    """Cash $8.40 on an $8.00 order clamps sale to $8.00, banks $0.40 as tip."""
    order_id = await _seed_eight_dollar_order(ledger)

    req = CashPaymentRequest(
        order_id=order_id,
        amount=8.40,           # inflated by frontend's stale TAX_RATE
        tip=0.0,
        payment_method="cash",
    )
    result = await process_cash_payment(req, ledger=ledger)
    assert result["success"] is True

    events = await ledger.get_events_by_correlation(order_id)
    order = project_order(events)

    assert len(order.payments) == 1
    p = order.payments[0]
    assert p.amount == pytest.approx(8.00)     # clamped to balance_due
    assert p.tip_amount == pytest.approx(0.40) # overage banked as tip
    assert order.is_fully_paid

    # The whole-day aggregation still balances: 8.00 cash == 8.00 net + 0 tax.
    agg = _aggregate_orders([order], {p.payment_id: p.tip_amount})
    tr = check_tender_reconciliation(
        cash_total=float(agg["cash_total"]),
        card_total=float(agg["card_total"]),
        net_sales=float(agg["net_sales"]),
        tax_collected=float(agg["tax_total"]),
    )
    assert tr.ok, tr.message

    # Tips partition: $0.40 cash tip accounted for.
    tp = check_tips_partition(
        total_tips=float(agg["total_tips"]),
        card_tips=float(agg["card_tips"]),
        cash_tips=float(agg["cash_tips"]),
    )
    assert tp.ok, tp.message
    assert float(agg["cash_tips"]) == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_cash_exact_payment_records_no_tip(ledger):
    """Control: paying exactly the balance_due banks no implicit tip."""
    order_id = await _seed_eight_dollar_order(ledger, order_id="o_guard_02")

    req = CashPaymentRequest(
        order_id=order_id,
        amount=8.00,
        tip=0.0,
        payment_method="cash",
    )
    await process_cash_payment(req, ledger=ledger)

    events = await ledger.get_events_by_correlation(order_id)
    order = project_order(events)
    p = order.payments[0]
    assert p.amount == pytest.approx(8.00)
    assert p.tip_amount == pytest.approx(0.00)


@pytest.mark.asyncio
async def test_cash_explicit_tip_and_overage_combine(ledger):
    """Explicit `tip=0.50` plus $0.40 overage = $0.90 total tip on that payment."""
    order_id = await _seed_eight_dollar_order(ledger, order_id="o_guard_03")

    req = CashPaymentRequest(
        order_id=order_id,
        amount=8.40,          # $0.40 overage
        tip=0.50,             # explicit tip on top
        payment_method="cash",
    )
    await process_cash_payment(req, ledger=ledger)

    events = await ledger.get_events_by_correlation(order_id)
    order = project_order(events)
    p = order.payments[0]
    assert p.amount == pytest.approx(8.00)
    assert p.tip_amount == pytest.approx(0.90)


# ── dual-pricing interaction ────────────────────────────────────────────────

class TestDualPricingGuard:
    """The cash dual-pricing discount runs before the overpayment clamp —
    so the clamp uses the POST-discount `balance_due`. These tests prove
    the two mechanisms compose correctly in every corner:

    - customer pays exactly the cash price (discount absorbs the gap)
    - customer pays the card price in cash (over-tendered — overage → tip)
    - customer pays less than cash price (partial payment, no overpayment)

    Backend invariants must hold for the full day aggregation in each.
    """

    @pytest.fixture(autouse=True)
    def _cash_discount_on(self, monkeypatch):
        # 4% cash dual-pricing (the repo default) with 0 tax so the math
        # is easy to read: $10 item → cash price $9.60, card price $10.00.
        monkeypatch.setattr(settings, "tax_rate", 0.0)
        monkeypatch.setattr(settings, "cash_discount_rate", 0.04)

    async def _seed_ten_dollar_order(self, ledger, order_id):
        await ledger.append(order_created(
            terminal_id=TERMINAL,
            order_id=order_id,
            order_type="dine_in",
            guest_count=1,
            correlation_id=order_id,
        ))
        await ledger.append(item_added(
            terminal_id=TERMINAL,
            order_id=order_id,
            item_id="it_dp",
            menu_item_id="m1",
            name="Item",
            price=10.00,
            quantity=1,
        ))
        return order_id

    @pytest.mark.asyncio
    async def test_cash_price_exact(self, ledger):
        """Customer pays the advertised cash price ($9.60); discount closes
        the $0.40 gap; no overage, no tip, order is fully paid."""
        order_id = await self._seed_ten_dollar_order(ledger, "o_dp_01")

        req = CashPaymentRequest(
            order_id=order_id,
            amount=9.60,
            tip=0.0,
            payment_method="cash",
        )
        await process_cash_payment(req, ledger=ledger)

        events = await ledger.get_events_by_correlation(order_id)
        order = project_order(events)
        assert order.is_fully_paid
        assert order.payments[0].amount == pytest.approx(9.60)
        assert order.payments[0].tip_amount == pytest.approx(0.00)
        # $0.40 dual-pricing discount is what closed the gap, not a tip.
        assert order.discount_total == pytest.approx(0.40)

        # Reconciliation: cash $9.60 == net $9.60 + tax $0.00.
        agg = _aggregate_orders([order], {})
        tr = check_tender_reconciliation(
            cash_total=float(agg["cash_total"]),
            card_total=float(agg["card_total"]),
            net_sales=float(agg["net_sales"]),
            tax_collected=float(agg["tax_total"]),
        )
        assert tr.ok, tr.message

    @pytest.mark.asyncio
    async def test_cash_at_card_price_no_discount(self, ledger):
        """Customer hands exactly the CARD price in cash. The dual-pricing
        discount only triggers when the tender equals the reduced cash
        price (naive_discount > 0), so the order is paid at full card
        price with no discount — matches the convenience-store behaviour
        where the customer didn't ask for the cash break."""
        order_id = await self._seed_ten_dollar_order(ledger, "o_dp_02")

        req = CashPaymentRequest(
            order_id=order_id,
            amount=10.00,
            tip=0.0,
            payment_method="cash",
        )
        await process_cash_payment(req, ledger=ledger)

        events = await ledger.get_events_by_correlation(order_id)
        order = project_order(events)
        p = order.payments[0]
        assert p.amount == pytest.approx(10.00)
        assert p.tip_amount == pytest.approx(0.00)
        assert order.discount_total == pytest.approx(0.00)
        assert order.is_fully_paid

    @pytest.mark.asyncio
    async def test_cash_overpaid_above_card_price(self, ledger):
        """Customer hands $11 cash on a $10 order — over even the card
        price. No dual-pricing discount (naive_discount would be negative),
        but the clamp routes the $1 overage into tip so the tender identity
        still holds."""
        order_id = await self._seed_ten_dollar_order(ledger, "o_dp_02b")

        req = CashPaymentRequest(
            order_id=order_id,
            amount=11.00,
            tip=0.0,
            payment_method="cash",
        )
        await process_cash_payment(req, ledger=ledger)

        events = await ledger.get_events_by_correlation(order_id)
        order = project_order(events)
        p = order.payments[0]
        assert p.amount == pytest.approx(10.00)       # clamped to balance_due
        assert p.tip_amount == pytest.approx(1.00)    # overage → tip
        assert order.discount_total == pytest.approx(0.00)
        assert order.is_fully_paid

        agg = _aggregate_orders([order], {p.payment_id: p.tip_amount})
        tr = check_tender_reconciliation(
            cash_total=float(agg["cash_total"]),
            card_total=float(agg["card_total"]),
            net_sales=float(agg["net_sales"]),
            tax_collected=float(agg["tax_total"]),
        )
        assert tr.ok, tr.message
        tp = check_tips_partition(
            total_tips=float(agg["total_tips"]),
            card_tips=float(agg["card_tips"]),
            cash_tips=float(agg["cash_tips"]),
        )
        assert tp.ok, tp.message

    @pytest.mark.asyncio
    async def test_cash_underpaid_partial(self, ledger):
        """Customer hands $5.00 on a $10 order; dual-pricing discount
        caps at `amount * rate / (1 - rate)`, sale leg is the full $5,
        no overage, partial payment leaves a remaining balance."""
        order_id = await self._seed_ten_dollar_order(ledger, "o_dp_03")

        req = CashPaymentRequest(
            order_id=order_id,
            amount=5.00,
            tip=0.0,
            payment_method="cash",
        )
        await process_cash_payment(req, ledger=ledger)

        events = await ledger.get_events_by_correlation(order_id)
        order = project_order(events)
        p = order.payments[0]
        # No clamp: request stayed below balance_due.
        assert p.amount == pytest.approx(5.00)
        assert p.tip_amount == pytest.approx(0.00)
        assert not order.is_fully_paid
        assert order.balance_due > 0

        # Invariants hold even mid-tender.
        agg = _aggregate_orders([order], {})
        tr = check_tender_reconciliation(
            cash_total=float(agg["cash_total"]),
            card_total=float(agg["card_total"]),
            net_sales=float(agg["net_sales"]),
            tax_collected=float(agg["tax_total"]),
        )
        # Partially-paid orders don't close so they're skipped from
        # total_checks but their cash_total is still counted. Aggregator
        # excludes `open` from net_sales, so cash_total should match 0
        # (no closed/paid orders for this test's single order).
        assert tr.ok, tr.message
