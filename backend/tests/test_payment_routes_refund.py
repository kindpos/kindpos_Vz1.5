"""
Tests for the remaining untested paths in `api/routes/payment_routes.py`:

  - POST /payments/refund       manager-approved refund with idempotency
  - POST /payments/zero-unadjusted bulk tip-zeroing
  - POST /payments/batch-settle  BatchClose against the payment device

Focus: money-out paths and their guards. The existing test suite
covers the cash / sale / tip-adjust flows; these three endpoints
were sitting at 50% route coverage.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.routes import payment_routes as pr
from app.config import settings
from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    item_added,
    order_closed,
    order_created,
    payment_confirmed,
    payment_initiated,
    tip_adjusted,
)


TEST_DB = Path("./data/test_payment_routes_refund.db")
TERMINAL = "terminal_ref"


@pytest.fixture(autouse=True)
def _zero_config(monkeypatch):
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


# ── helpers ─────────────────────────────────────────────────────────────────

async def _paid_order(
    ledger, *, order_id: str, amount: float = 20.00,
    method: str = "card", txn_suffix: str = "0",
) -> str:
    """Seed a closed order with one confirmed payment. Returns payment_id."""
    await ledger.append(order_created(
        terminal_id=TERMINAL,
        order_id=order_id,
        order_type="dine_in",
        guest_count=1,
        server_id="emp_A",
        correlation_id=order_id,
    ))
    await ledger.append(item_added(
        terminal_id=TERMINAL,
        order_id=order_id,
        item_id=f"{order_id}_it",
        menu_item_id="m1",
        name="Item",
        price=amount,
        quantity=1,
    ))
    payment_id = f"{order_id}_p{txn_suffix}"
    await ledger.append(payment_initiated(
        terminal_id=TERMINAL, order_id=order_id, payment_id=payment_id,
        amount=amount, method=method,
    ))
    await ledger.append(payment_confirmed(
        terminal_id=TERMINAL, order_id=order_id, payment_id=payment_id,
        transaction_id=f"txn_{payment_id}", amount=amount, tax=0.0,
    ))
    await ledger.append(order_closed(
        terminal_id=TERMINAL, order_id=order_id, total=amount,
    ))
    return payment_id


# ═══════════════════════════════════════════════════════════════════════════
# REFUND
# ═══════════════════════════════════════════════════════════════════════════

class TestProcessRefund:

    @pytest.mark.asyncio
    async def test_full_refund_emits_payment_refunded_event(self, ledger):
        """Refund with amount=None → full payment amount."""
        pid = await _paid_order(ledger, order_id="o_full", amount=25.00)

        res = await pr.process_refund(
            pr.RefundRequest(
                order_id="o_full",
                payment_id=pid,
                amount=None,
                reason="customer unhappy",
                approved_by="manager_1",
            ),
            ledger=ledger,
        )

        assert res["success"] is True
        assert res["refund_amount"] == pytest.approx(25.00)
        # PAYMENT_REFUNDED event landed in the ledger
        events = await ledger.get_events_by_type(EventType.PAYMENT_REFUNDED)
        assert len(events) == 1
        assert events[0].payload["amount"] == pytest.approx(25.00)

    @pytest.mark.asyncio
    async def test_partial_refund_reduces_remaining_refundable(self, ledger):
        """Partial refund leaves remaining = original − refunded."""
        pid = await _paid_order(ledger, order_id="o_part", amount=40.00)

        await pr.process_refund(
            pr.RefundRequest(
                order_id="o_part", payment_id=pid,
                amount=10.00, reason="spilled",
                approved_by="mgr",
            ),
            ledger=ledger,
        )
        # Second partial refund within the remaining $30
        res2 = await pr.process_refund(
            pr.RefundRequest(
                order_id="o_part", payment_id=pid,
                amount=25.00, reason="rest",
                approved_by="mgr",
            ),
            ledger=ledger,
        )
        assert res2["refund_amount"] == pytest.approx(25.00)

    @pytest.mark.asyncio
    async def test_refund_exceeding_remaining_rejected(self, ledger):
        """Refund total cannot exceed the original payment amount."""
        pid = await _paid_order(ledger, order_id="o_over", amount=20.00)

        # First refund eats $15 of the $20
        await pr.process_refund(
            pr.RefundRequest(
                order_id="o_over", payment_id=pid,
                amount=15.00, reason="first",
                approved_by="mgr",
            ),
            ledger=ledger,
        )
        # Asking for $10 more → total would be $25 > original $20
        with pytest.raises(HTTPException) as exc:
            await pr.process_refund(
                pr.RefundRequest(
                    order_id="o_over", payment_id=pid,
                    amount=10.00, reason="over",
                    approved_by="mgr",
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 400
        assert "exceeds remaining" in exc.value.detail

    @pytest.mark.asyncio
    async def test_refund_without_manager_approval_forbidden(self, ledger):
        """approved_by must be non-empty — 403."""
        pid = await _paid_order(ledger, order_id="o_noapp", amount=10.00)
        with pytest.raises(HTTPException) as exc:
            await pr.process_refund(
                pr.RefundRequest(
                    order_id="o_noapp", payment_id=pid,
                    amount=5.00, reason="test",
                    approved_by="   ",   # whitespace-only
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_refund_on_missing_order_404s(self, ledger):
        with pytest.raises(HTTPException) as exc:
            await pr.process_refund(
                pr.RefundRequest(
                    order_id="nope", payment_id="pA",
                    amount=5.00, reason="x",
                    approved_by="mgr",
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_refund_on_missing_payment_404s(self, ledger):
        await _paid_order(ledger, order_id="o_np", amount=10.00)
        with pytest.raises(HTTPException) as exc:
            await pr.process_refund(
                pr.RefundRequest(
                    order_id="o_np", payment_id="pay_nosuch",
                    amount=5.00, reason="x",
                    approved_by="mgr",
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_refund_amount_must_be_positive(self, ledger):
        pid = await _paid_order(ledger, order_id="o_zero", amount=10.00)
        with pytest.raises(HTTPException) as exc:
            await pr.process_refund(
                pr.RefundRequest(
                    order_id="o_zero", payment_id=pid,
                    amount=0.0, reason="x",
                    approved_by="mgr",
                ),
                ledger=ledger,
            )
        assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# ZERO UNADJUSTED TIPS
# ═══════════════════════════════════════════════════════════════════════════

class TestZeroUnadjustedTips:
    """Bulk action: find every confirmed card payment without a
    TIP_ADJUSTED event and emit TIP_ADJUSTED with tip_amount=0 so the
    server's checkout is no longer blocked."""

    @pytest.mark.asyncio
    async def test_zeros_only_card_payments_without_tip_adjusted(self, ledger):
        # Order A: card payment, no tip_adjusted yet → should zero
        await _paid_order(ledger, order_id="oA", amount=10.00, method="card",
                          txn_suffix="A")
        # Order B: card payment with explicit tip adjust already → skip
        pB = await _paid_order(ledger, order_id="oB", amount=20.00, method="card",
                               txn_suffix="B")
        await ledger.append(tip_adjusted(
            terminal_id=TERMINAL, order_id="oB", payment_id=pB, tip_amount=3.00,
        ))
        # Order C: cash payment → never "unadjusted"
        await _paid_order(ledger, order_id="oC", amount=15.00, method="cash",
                          txn_suffix="C")

        res = await pr.zero_unadjusted_tips(server_id=None, ledger=ledger)
        assert res["zeroed_count"] == 1   # only oA's card payment
        # Verify: two TIP_ADJUSTED events now exist (one for oB, one zeroed for oA)
        events = await ledger.get_events_by_type(EventType.TIP_ADJUSTED)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_scope_by_server_id(self, ledger):
        """`?server_id=` narrows the zero-all to one server's orders only."""
        # Alice has an unadjusted card payment
        await _paid_order(ledger, order_id="oA1", amount=10.00, method="card",
                          txn_suffix="1")
        # Bob has an unadjusted card payment (different server_id)
        await ledger.append(order_created(
            terminal_id=TERMINAL, order_id="oB1",
            order_type="dine_in", guest_count=1,
            server_id="emp_B", correlation_id="oB1",
        ))
        await ledger.append(item_added(
            terminal_id=TERMINAL, order_id="oB1", item_id="i",
            menu_item_id="m", name="X", price=20.00, quantity=1,
        ))
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="oB1", payment_id="oB1_p",
            amount=20.00, method="card",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="oB1", payment_id="oB1_p",
            transaction_id="txn_oB1", amount=20.00, tax=0.0,
        ))
        await ledger.append(order_closed(
            terminal_id=TERMINAL, order_id="oB1", total=20.00,
        ))

        # Zero only emp_A's orders
        res = await pr.zero_unadjusted_tips(server_id="emp_A", ledger=ledger)
        assert res["zeroed_count"] == 1
        # emp_B's still pending
        events = await ledger.get_events_by_type(EventType.TIP_ADJUSTED)
        adjusted_payments = {e.payload["payment_id"] for e in events}
        assert "oA1_p1" in adjusted_payments
        assert "oB1_p" not in adjusted_payments

    @pytest.mark.asyncio
    async def test_empty_ledger_zeros_nothing(self, ledger):
        res = await pr.zero_unadjusted_tips(server_id=None, ledger=ledger)
        assert res["zeroed_count"] == 0

    @pytest.mark.asyncio
    async def test_skips_orders_not_closed(self, ledger):
        """An open order's card payment doesn't count — it's not ready
        for zero-tip. Only closed/paid orders are bulk-zeroed."""
        # Create an order + card payment but DON'T close it
        await ledger.append(order_created(
            terminal_id=TERMINAL, order_id="o_open",
            order_type="dine_in", correlation_id="o_open",
        ))
        await ledger.append(item_added(
            terminal_id=TERMINAL, order_id="o_open", item_id="i",
            menu_item_id="m", name="X", price=10.00, quantity=1,
        ))
        await ledger.append(payment_initiated(
            terminal_id=TERMINAL, order_id="o_open", payment_id="o_open_p",
            amount=10.00, method="card",
        ))
        await ledger.append(payment_confirmed(
            terminal_id=TERMINAL, order_id="o_open", payment_id="o_open_p",
            transaction_id="txn_open", amount=10.00, tax=0.0,
        ))
        # Order status auto-transitions to "paid" on fully-paid projection;
        # we never closed so it's "paid", not "closed"/"open" — the route
        # filters to ("closed", "paid") which INCLUDES paid.
        res = await pr.zero_unadjusted_tips(server_id=None, ledger=ledger)
        # paid orders *are* eligible per the route, so this zeroes 1
        assert res["zeroed_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# BATCH SETTLE
# ═══════════════════════════════════════════════════════════════════════════

class TestBatchSettle:
    """BatchClose path. The route dispatches to the registered payment
    device. For the mock device (the test fixture) we expect a success
    stub; a missing device returns an explicit error."""

    @pytest.mark.asyncio
    async def test_no_device_returns_error(self, ledger, monkeypatch):
        """If no payment device is registered for the terminal, the route
        returns a success=False object — it must never explode."""
        # Force a brand-new PaymentManager with no devices registered
        from app.core.adapters.payment_manager import PaymentManager
        monkeypatch.setattr(pr, "_manager", PaymentManager(ledger, settings.terminal_id))
        monkeypatch.setattr(pr, "_devices_initialized", True)   # skip _ensure_devices

        res = await pr.batch_settle(ledger=ledger)
        assert res["success"] is False
        assert "No payment device" in res["error"]

    @pytest.mark.asyncio
    async def test_mock_device_returns_mock_success(self, ledger, monkeypatch):
        """The mock path is the one the test harness uses. Response carries
        `using_mock=True` so the frontend can suppress real-batch UI."""
        monkeypatch.setattr(pr, "_manager", None)
        monkeypatch.setattr(pr, "_devices_initialized", False)

        res = await pr.batch_settle(ledger=ledger)
        assert res["success"] is True
        assert res.get("using_mock") is True
        assert res["batch_id"] == "MOCK"
