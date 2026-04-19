"""
KINDpos Comprehensive POS System Tests
========================================
Covers 7 critical areas:
  1. Financial accuracy (tax, discounts, split payments, tips, rounding)
  2. Transaction flow (lifecycle, voids, refunds, comps, re-opens)
  3. Hardware integration (payment validation, print queue)
  4. Concurrency and load (parallel appends, rapid orders, projection at scale)
  5. Reporting and reconciliation (day summary, tips, batch settlement)
  6. Offline / resilience (WAL crash recovery, sync tracking, print queue durability)
  7. User flow and permissions (clock in/out, RBAC gaps, tip ceiling approval)
"""

import asyncio
import os
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    create_event,
    order_created,
    item_added,
    item_removed,
    item_modified,
    item_sent,
    modifier_applied,
    payment_initiated,
    payment_confirmed,
    payment_failed,
    order_closed,
    order_reopened,
    order_voided,
    tip_adjusted,
    batch_submitted,
    day_closed,
    user_logged_in,
    user_logged_out,
    cash_refund_due,
)
from app.core.projections import project_order, project_orders, Order
from app.core.money import money_round

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TAX_RATE = 0.07
TERMINAL = "T-TEST"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def ledger(tmp_path):
    db_path = str(tmp_path / "test_pos.db")
    async with EventLedger(db_path) as _ledger:
        yield _ledger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oid() -> str:
    return f"order_{uuid.uuid4().hex[:12]}"


def _pid() -> str:
    return f"pay_{uuid.uuid4().hex[:8]}"


async def _create_order(ledger, order_id, table="T1", server_id="srv-1",
                        server_name="Alice", guest_count=1):
    evt = order_created(
        terminal_id=TERMINAL, order_id=order_id,
        table=table, server_id=server_id, server_name=server_name,
        guest_count=guest_count,
    )
    evt = evt.model_copy(update={"correlation_id": order_id})
    await ledger.append(evt)


async def _add_item(ledger, order_id, item_id, name, price,
                    quantity=1, category="food"):
    evt = item_added(
        terminal_id=TERMINAL, order_id=order_id,
        item_id=item_id, menu_item_id=f"menu-{item_id}",
        name=name, price=price, quantity=quantity, category=category,
    )
    await ledger.append(evt)


async def _send_item(ledger, order_id, item_id, name):
    evt = item_sent(
        terminal_id=TERMINAL, order_id=order_id,
        item_id=item_id, name=name,
    )
    await ledger.append(evt)


async def _pay(ledger, order_id, payment_id, amount, method="card"):
    init = payment_initiated(
        terminal_id=TERMINAL, order_id=order_id,
        payment_id=payment_id, amount=amount, method=method,
    )
    await ledger.append(init)
    conf = payment_confirmed(
        terminal_id=TERMINAL, order_id=order_id,
        payment_id=payment_id, transaction_id=f"txn_{payment_id}",
        amount=amount,
    )
    await ledger.append(conf)


async def _close_order(ledger, order_id, total):
    evt = order_closed(terminal_id=TERMINAL, order_id=order_id, total=total)
    await ledger.append(evt)


def _project(events, tax_rate=TAX_RATE):
    return project_order(events, tax_rate=tax_rate)


async def _get_order(ledger, order_id):
    events = await ledger.get_events_by_correlation(order_id)
    return _project(events)


# ═══════════════════════════════════════════════════════════════════════════
# 1. FINANCIAL ACCURACY
# ═══════════════════════════════════════════════════════════════════════════

class TestFinancialAccuracy:
    """Verify tax calculations, discounts, split payments, tip math, and
    rounding all land to the penny."""

    @pytest.mark.asyncio
    async def test_tax_on_single_item(self, ledger):
        """10.00 * 0.07 = 0.70  →  total = 10.70"""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 10.00
        assert order.tax == 0.70
        assert order.total == 10.70

    @pytest.mark.asyncio
    async def test_tax_after_flat_discount(self, ledger):
        """$50 item – $5 discount → tax on $45 = 3.15 → total = 48.15"""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Steak", 50.00)
        disc = create_event(
            event_type=EventType.DISCOUNT_APPROVED,
            terminal_id=TERMINAL,
            payload={"discount_type": "comp", "amount": 5.00,
                     "reason": "manager comp", "approved_by": "mgr"},
            correlation_id=oid,
        )
        await ledger.append(disc)
        order = await _get_order(ledger, oid)
        assert order.discount_total == 5.00
        assert order.tax == money_round(45.00 * TAX_RATE)  # 3.15
        assert order.total == money_round(50.00 - 5.00 + 45.00 * TAX_RATE)  # 48.15

    @pytest.mark.asyncio
    async def test_tax_rounding_half_up(self, ledger):
        """$10.05 * 0.07 = 0.7035 → rounds to 0.70 (ROUND_HALF_UP)."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Appetizer", 10.05)
        order = await _get_order(ledger, oid)
        assert order.tax == money_round(10.05 * TAX_RATE)  # 0.70
        assert order.total == money_round(10.05 + 10.05 * TAX_RATE)  # 10.75

    @pytest.mark.asyncio
    async def test_modifier_pricing_with_quantity(self, ledger):
        """Item $10 + modifier $1.50, qty 2 → subtotal = (10+1.50)*2 = 23.00"""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00, quantity=2)
        mod_evt = modifier_applied(
            terminal_id=TERMINAL, order_id=oid, item_id="i1",
            modifier_id="mod1", modifier_name="Extra Cheese",
            modifier_price=1.50,
        )
        await ledger.append(mod_evt)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 23.00

    @pytest.mark.asyncio
    async def test_split_payment_balance_tracking(self, ledger):
        """Two partial payments, verify balance_due decreases correctly."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Steak", 50.00)
        order = await _get_order(ledger, oid)
        full = order.total  # 53.50

        await _pay(ledger, oid, "p1", 20.00)
        order = await _get_order(ledger, oid)
        assert order.amount_paid == 20.00
        assert order.balance_due == money_round(full - 20.00)

        await _pay(ledger, oid, "p2", 33.50)
        order = await _get_order(ledger, oid)
        assert order.amount_paid == 53.50
        assert order.balance_due == 0.00
        assert order.is_fully_paid

    @pytest.mark.asyncio
    async def test_split_payment_three_way(self, ledger):
        """Three payments totaling exact amount → fully paid."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Dinner", 30.00)
        order = await _get_order(ledger, oid)
        full = order.total  # 32.10

        await _pay(ledger, oid, "p1", 10.70, method="card")
        await _pay(ledger, oid, "p2", 10.70, method="card")
        await _pay(ledger, oid, "p3", 10.70, method="cash")
        order = await _get_order(ledger, oid)
        assert order.amount_paid == 32.10
        assert order.is_fully_paid
        assert order.status == "paid"

    @pytest.mark.asyncio
    async def test_overpayment_negative_balance(self, ledger):
        """Cash overpayment → negative balance_due (change owed)."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Coffee", 5.00)
        order = await _get_order(ledger, oid)
        total = order.total  # 5.35

        await _pay(ledger, oid, "p1", 10.00, method="cash")
        order = await _get_order(ledger, oid)
        assert order.balance_due == money_round(total - 10.00)  # -4.65
        assert order.balance_due < 0

    @pytest.mark.asyncio
    async def test_penny_accumulation_100_items(self, ledger):
        """100 items at $0.01 each → subtotal = $1.00 exactly."""
        oid = _oid()
        await _create_order(ledger, oid)
        for i in range(100):
            await _add_item(ledger, oid, f"i{i}", "Penny item", 0.01)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 1.00

    @pytest.mark.asyncio
    async def test_discount_exceeding_subtotal_clamped(self, ledger):
        """$5 discount on $3 item → taxable clamped to 0, total = 0."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Side", 3.00)
        disc = create_event(
            event_type=EventType.DISCOUNT_APPROVED,
            terminal_id=TERMINAL,
            payload={"discount_type": "comp", "amount": 5.00,
                     "reason": "full comp", "approved_by": "mgr"},
            correlation_id=oid,
        )
        await ledger.append(disc)
        order = await _get_order(ledger, oid)
        assert order.discount_total == 5.00
        assert order.tax == 0.00  # taxable clamped to 0
        assert order.total == 0.00  # total clamped to 0

    @pytest.mark.asyncio
    async def test_tip_precision_rounding(self, ledger):
        """Tip of 2.6666666 rounds to 2.67 via money_round."""
        assert money_round(2.6666666) == 2.67
        assert money_round(2.665) == 2.67  # half-up
        assert money_round(2.664) == 2.66


# ═══════════════════════════════════════════════════════════════════════════
# 2. TRANSACTION FLOW
# ═══════════════════════════════════════════════════════════════════════════

class TestTransactionFlow:
    """Full lifecycle, voids, refunds, comps, and re-opens."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, ledger):
        """create → add → send → pay → close, verify each state."""
        oid = _oid()
        await _create_order(ledger, oid)
        order = await _get_order(ledger, oid)
        assert order.status == "open"

        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _send_item(ledger, oid, "i1", "Burger")
        order = await _get_order(ledger, oid)
        assert order.items[0].sent is True

        await _pay(ledger, oid, "p1", order.total)
        order = await _get_order(ledger, oid)
        assert order.status == "paid"

        await _close_order(ledger, oid, order.total)
        order = await _get_order(ledger, oid)
        assert order.status == "closed"

    @pytest.mark.asyncio
    async def test_void_order_with_reason(self, ledger):
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        evt = order_voided(
            terminal_id=TERMINAL, order_id=oid,
            reason="customer walked out", approved_by="mgr-1",
        )
        await ledger.append(evt)
        order = await _get_order(ledger, oid)
        assert order.status == "voided"
        assert order.void_reason == "customer walked out"
        assert order.voided_at is not None

    @pytest.mark.asyncio
    async def test_void_api_rejects_without_manager(self, ledger):
        """Void API route requires approved_by — rejects empty string."""
        from fastapi import HTTPException
        from app.api.routes.orders import void_order, VoidOrderRequest

        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)

        # Pydantic now requires approved_by as a non-optional str,
        # but even if passed as empty the route rejects it
        with pytest.raises(HTTPException) as exc_info:
            req = VoidOrderRequest(reason="test void", approved_by="")
            await void_order(oid, req, ledger)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reopen_after_close(self, ledger):
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _close_order(ledger, oid, 10.70)
        order = await _get_order(ledger, oid)
        assert order.status == "closed"

        evt = order_reopened(terminal_id=TERMINAL, order_id=oid)
        await ledger.append(evt)
        order = await _get_order(ledger, oid)
        assert order.status == "open"
        assert order.closed_at is None

    @pytest.mark.asyncio
    async def test_item_removed_reduces_subtotal(self, ledger):
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _add_item(ledger, oid, "i2", "Fries", 5.00)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 15.00

        evt = item_removed(terminal_id=TERMINAL, order_id=oid, item_id="i1")
        await ledger.append(evt)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 5.00
        assert len(order.items) == 1

    @pytest.mark.asyncio
    async def test_comp_as_discount(self, ledger):
        """DISCOUNT_APPROVED with type=comp reduces total."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Wine", 14.00)
        disc = create_event(
            event_type=EventType.DISCOUNT_APPROVED,
            terminal_id=TERMINAL,
            payload={"discount_type": "comp", "amount": 14.00,
                     "reason": "full comp", "approved_by": "mgr"},
            correlation_id=oid,
        )
        await ledger.append(disc)
        order = await _get_order(ledger, oid)
        assert order.discount_total == 14.00
        assert order.total == money_round(0 + 0 * TAX_RATE)  # 0.00

    @pytest.mark.asyncio
    async def test_modifier_add_then_remove(self, ledger):
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)

        add_mod = modifier_applied(
            terminal_id=TERMINAL, order_id=oid, item_id="i1",
            modifier_id="m1", modifier_name="Bacon", modifier_price=2.00,
        )
        await ledger.append(add_mod)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 12.00

        rm_mod = modifier_applied(
            terminal_id=TERMINAL, order_id=oid, item_id="i1",
            modifier_id="m1", modifier_name="Bacon", modifier_price=2.00,
            action="remove",
        )
        await ledger.append(rm_mod)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 10.00

    @pytest.mark.asyncio
    async def test_payment_failed_not_counted(self, ledger):
        """PAYMENT_FAILED should not increase amount_paid."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)

        init = payment_initiated(
            terminal_id=TERMINAL, order_id=oid,
            payment_id="p1", amount=10.70, method="card",
        )
        await ledger.append(init)
        fail = payment_failed(
            terminal_id=TERMINAL, order_id=oid,
            payment_id="p1", error="declined",
        )
        await ledger.append(fail)
        order = await _get_order(ledger, oid)
        assert order.amount_paid == 0.00
        assert order.payments[0].status == "failed"
        assert order.status == "open"

    @pytest.mark.asyncio
    async def test_refund_full_payment(self, ledger):
        """Full refund on a confirmed cash payment via refund endpoint."""
        from app.api.routes.payment_routes import process_refund, RefundRequest

        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _pay(ledger, oid, "p1", 10.70, method="cash")

        req = RefundRequest(
            order_id=oid, payment_id="p1",
            reason="Customer complaint", approved_by="mgr-1",
        )
        result = await process_refund(req, ledger)
        assert result["success"] is True
        assert result["refund_amount"] == 10.70

        # Verify PAYMENT_REFUNDED event in ledger
        events = await ledger.get_events_by_correlation(oid)
        refunds = [e for e in events if e.event_type == EventType.PAYMENT_REFUNDED]
        assert len(refunds) == 1
        assert refunds[0].payload["amount"] == 10.70

    @pytest.mark.asyncio
    async def test_refund_partial_amount(self, ledger):
        """Partial refund of $5 on a $10.70 payment."""
        from app.api.routes.payment_routes import process_refund, RefundRequest

        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _pay(ledger, oid, "p1", 10.70, method="cash")

        req = RefundRequest(
            order_id=oid, payment_id="p1", amount=5.00,
            reason="Partial refund", approved_by="mgr-1",
        )
        result = await process_refund(req, ledger)
        assert result["refund_amount"] == 5.00

    @pytest.mark.asyncio
    async def test_refund_exceeding_payment_rejected(self, ledger):
        """Refund > original payment amount → rejected."""
        from fastapi import HTTPException
        from app.api.routes.payment_routes import process_refund, RefundRequest

        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _pay(ledger, oid, "p1", 10.70, method="cash")

        with pytest.raises(HTTPException) as exc_info:
            req = RefundRequest(
                order_id=oid, payment_id="p1", amount=20.00,
                reason="Too much", approved_by="mgr-1",
            )
            await process_refund(req, ledger)
        assert exc_info.value.status_code == 400
        assert "exceeds" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_refund_requires_manager_approval(self, ledger):
        """Refund without manager → 403."""
        from fastapi import HTTPException
        from app.api.routes.payment_routes import process_refund, RefundRequest

        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _pay(ledger, oid, "p1", 10.70, method="cash")

        with pytest.raises(HTTPException) as exc_info:
            req = RefundRequest(
                order_id=oid, payment_id="p1",
                reason="refund", approved_by="",
            )
            await process_refund(req, ledger)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_double_close_idempotent(self, ledger):
        """Closing an already-closed order should not corrupt state."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        await _pay(ledger, oid, "p1", 10.70)
        await _close_order(ledger, oid, 10.70)
        await _close_order(ledger, oid, 10.70)  # second close
        order = await _get_order(ledger, oid)
        assert order.status == "closed"
        assert order.total == 10.70


# ═══════════════════════════════════════════════════════════════════════════
# 3. HARDWARE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

class TestHardwareIntegration:
    """Payment validation rules and print queue persistence."""

    @pytest.mark.asyncio
    async def test_validator_rejects_zero_amount(self, ledger):
        """Rule 1: amount <= 0 → REJECTED."""
        from app.core.adapters.payment_validator import PaymentValidator
        from app.core.adapters.base_payment import TransactionRequest, ValidationStatus

        validator = PaymentValidator(ledger)
        req = TransactionRequest(
            terminal_id=TERMINAL, order_id="o1",
            amount=Decimal("0.00"),
        )
        result = await validator.validate(req, device=None)
        assert result.status == ValidationStatus.REJECTED
        assert "greater than zero" in result.reason

    @pytest.mark.asyncio
    async def test_validator_rejects_negative_tip(self, ledger):
        """Rule 2: tip < 0 → REJECTED."""
        from app.core.adapters.payment_validator import PaymentValidator
        from app.core.adapters.base_payment import TransactionRequest, ValidationStatus

        validator = PaymentValidator(ledger)
        req = TransactionRequest(
            terminal_id=TERMINAL, order_id="o1",
            amount=Decimal("10.00"),
            tip_amount=Decimal("-1.00"),
        )
        result = await validator.validate(req, device=None)
        assert result.status == ValidationStatus.REJECTED
        assert "negative" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_validator_tip_ceiling_needs_approval(self, ledger):
        """Rule 5: tip > 50% of sale → NEEDS_APPROVAL."""
        from app.core.adapters.payment_validator import PaymentValidator
        from app.core.adapters.base_payment import TransactionRequest, ValidationStatus

        validator = PaymentValidator(ledger)
        req = TransactionRequest(
            terminal_id=TERMINAL, order_id="o1",
            amount=Decimal("100.00"),
            tip_amount=Decimal("200.00"),  # 200% of sale
        )
        result = await validator.validate(req, device=None)
        assert result.status == ValidationStatus.NEEDS_APPROVAL
        assert "ceiling" in result.reason.lower() or "approval" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_validator_device_offline_rejected(self, ledger):
        """Rule 9: offline device → REJECTED."""
        from app.core.adapters.payment_validator import PaymentValidator
        from app.core.adapters.base_payment import (
            TransactionRequest, ValidationStatus, BasePaymentDevice,
            PaymentDeviceStatus, PaymentDeviceConfig, PaymentDeviceType,
        )
        from unittest.mock import MagicMock

        validator = PaymentValidator(ledger)
        device = MagicMock(spec=BasePaymentDevice)
        device.status = PaymentDeviceStatus.OFFLINE
        device.in_sacred_state = False
        device.config = MagicMock()
        device.config.name = "Test Device"

        req = TransactionRequest(
            terminal_id=TERMINAL, order_id="o1",
            amount=Decimal("10.00"),
        )
        result = await validator.validate(req, device=device)
        assert result.status == ValidationStatus.REJECTED
        assert "unavailable" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_validator_sacred_state_rejected(self, ledger):
        """Rule 9: device in sacred state (processing) → REJECTED."""
        from app.core.adapters.payment_validator import PaymentValidator
        from app.core.adapters.base_payment import (
            TransactionRequest, ValidationStatus, BasePaymentDevice,
            PaymentDeviceStatus,
        )
        from unittest.mock import MagicMock

        validator = PaymentValidator(ledger)
        device = MagicMock(spec=BasePaymentDevice)
        device.status = PaymentDeviceStatus.ONLINE
        device.in_sacred_state = True
        device.config = MagicMock()
        device.config.name = "Test Device"

        req = TransactionRequest(
            terminal_id=TERMINAL, order_id="o1",
            amount=Decimal("10.00"),
        )
        result = await validator.validate(req, device=device)
        assert result.status == ValidationStatus.REJECTED
        assert "busy" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_print_queue_enqueue_and_retrieve(self, tmp_path):
        """Print queue persists jobs in SQLite and retrieves them."""
        from app.printing.print_queue import PrintJobQueue

        queue = PrintJobQueue(str(tmp_path / "print_q.db"))
        await queue.connect()
        try:
            job_id = await queue.enqueue(
                order_id="o1", template_id="kitchen_ticket",
                printer_mac="AA:BB:CC:DD:EE:FF", ticket_number="KT-001",
                context={"items": [{"name": "Burger"}]},
            )
            pending = await queue.get_pending_jobs()
            assert len(pending) == 1
            assert pending[0]["job_id"] == job_id
            assert pending[0]["status"] == "queued"

            # Mark sent then failed, verify retry
            await queue.mark_sent(job_id, attempt_number=1)
            await queue.mark_failed(job_id)
            failed = await queue.get_failed_jobs()
            assert len(failed) == 1

            await queue.reset_for_retry(job_id)
            pending = await queue.get_pending_jobs()
            assert len(pending) == 1
            assert pending[0]["attempt_count"] == 0
        finally:
            await queue.close()


# ═══════════════════════════════════════════════════════════════════════════
# 4. CONCURRENCY AND LOAD
# ═══════════════════════════════════════════════════════════════════════════

class TestConcurrencyAndLoad:
    """Multiple terminals, rapid-fire orders, no lost or double-counted events."""

    @pytest.mark.asyncio
    async def test_concurrent_appends_unique_sequences(self, ledger):
        """20 concurrent appends all get unique sequence numbers."""
        oid = _oid()
        await _create_order(ledger, oid)

        async def append_item(idx):
            evt = item_added(
                terminal_id=TERMINAL, order_id=oid,
                item_id=f"item-{idx}", menu_item_id=f"menu-{idx}",
                name=f"Item {idx}", price=1.00,
            )
            return await ledger.append(evt)

        results = await asyncio.gather(*[append_item(i) for i in range(20)])
        seqs = [r.sequence_number for r in results]
        assert len(set(seqs)) == 20  # all unique

    @pytest.mark.asyncio
    async def test_concurrent_appends_hash_chain_valid(self, ledger):
        """After concurrent writes, hash chain verifies."""
        oid = _oid()
        await _create_order(ledger, oid)

        async def append_item(idx):
            evt = item_added(
                terminal_id=TERMINAL, order_id=oid,
                item_id=f"item-{idx}", menu_item_id=f"menu-{idx}",
                name=f"Item {idx}", price=1.00,
            )
            return await ledger.append(evt)

        await asyncio.gather(*[append_item(i) for i in range(20)])
        is_valid, first_invalid = await ledger.verify_chain()
        assert is_valid, f"Chain invalid starting at seq {first_invalid}"

    @pytest.mark.asyncio
    async def test_rapid_fire_50_orders(self, ledger):
        """Create 50 orders rapidly, all project correctly."""
        order_ids = []
        for i in range(50):
            oid = _oid()
            order_ids.append(oid)
            await _create_order(ledger, oid)
            await _add_item(ledger, oid, f"i-{i}", f"Item {i}", 10.00)

        events = await ledger.get_events_since(0, limit=50000)
        orders = project_orders(events)
        assert len(orders) == 50
        for oid in order_ids:
            assert oid in orders
            assert orders[oid].subtotal == 10.00

    @pytest.mark.asyncio
    async def test_concurrent_payments_no_cross_contamination(self, ledger):
        """Parallel payments on different orders don't cross-contaminate."""
        oids = [_oid() for _ in range(5)]
        for oid in oids:
            await _create_order(ledger, oid)
            await _add_item(ledger, oid, "i1", "Burger", 10.00)

        async def pay_order(oid, idx):
            await _pay(ledger, oid, f"p-{idx}", 10.70)

        await asyncio.gather(*[pay_order(oid, i) for i, oid in enumerate(oids)])

        for oid in oids:
            order = await _get_order(ledger, oid)
            assert order.amount_paid == 10.70
            assert len(order.payments) == 1

    @pytest.mark.asyncio
    async def test_event_ordering_preserved(self, ledger):
        """Events for same order replay in sequence_number order."""
        oid = _oid()
        await _create_order(ledger, oid)
        for i in range(10):
            await _add_item(ledger, oid, f"i{i}", f"Item {i}", 1.00)

        events = await ledger.get_events_by_correlation(oid)
        seqs = [e.sequence_number for e in events]
        assert seqs == sorted(seqs)

    @pytest.mark.asyncio
    async def test_high_volume_projection(self, ledger):
        """500+ events project correctly."""
        oid = _oid()
        await _create_order(ledger, oid)
        for i in range(200):
            await _add_item(ledger, oid, f"i{i}", f"Item {i}", 0.50)
        order = await _get_order(ledger, oid)
        assert order.subtotal == 100.00
        assert len(order.items) == 200


# ═══════════════════════════════════════════════════════════════════════════
# 5. REPORTING AND RECONCILIATION
# ═══════════════════════════════════════════════════════════════════════════

class TestReportingReconciliation:
    """Sales summaries, tip reports, batch settlements all match event data."""

    async def _seed_two_orders(self, ledger):
        """Seed two closed orders: one cash ($59 food), one card ($62 food)."""
        o1 = _oid()
        await _create_order(ledger, o1, server_id="srv-1", server_name="Alice")
        await _add_item(ledger, o1, "i1", "Steak", 45.00)
        await _add_item(ledger, o1, "i2", "Wine", 14.00)
        order1 = await _get_order(ledger, o1)
        await _pay(ledger, o1, "p1", order1.total, method="cash")
        await _close_order(ledger, o1, order1.total)

        o2 = _oid()
        await _create_order(ledger, o2, server_id="srv-1", server_name="Alice")
        await _add_item(ledger, o2, "i3", "Burger", 28.00)
        await _add_item(ledger, o2, "i4", "Salad", 16.00)
        await _add_item(ledger, o2, "i5", "Beer", 9.00)
        await _add_item(ledger, o2, "i6", "Beer", 9.00)
        order2 = await _get_order(ledger, o2)
        await _pay(ledger, o2, "p2", order2.total, method="card")
        tip_evt = tip_adjusted(
            terminal_id=TERMINAL, order_id=o2, payment_id="p2",
            tip_amount=12.40,
        )
        await ledger.append(tip_evt)
        await _close_order(ledger, o2, order2.total)

        return o1, o2, order1, order2

    @pytest.mark.asyncio
    async def test_day_summary_totals_match_projections(self, ledger):
        """Sum of projected totals matches manual aggregation."""
        o1, o2, order1, order2 = await self._seed_two_orders(ledger)
        events = await ledger.get_events_since(0, limit=50000)
        orders = project_orders(events)

        total_sales = sum(
            o.total for o in orders.values() if o.status in ("closed", "paid")
        )
        assert total_sales == money_round(order1.total + order2.total)

    @pytest.mark.asyncio
    async def test_voided_orders_excluded_from_net_sales(self, ledger):
        """Voided orders should not count toward net sales."""
        o1, o2, order1, order2 = await self._seed_two_orders(ledger)
        # Void order 1
        evt = order_voided(terminal_id=TERMINAL, order_id=o1, reason="test")
        await ledger.append(evt)

        events = await ledger.get_events_since(0, limit=50000)
        orders = project_orders(events)
        non_void = [o for o in orders.values() if o.status != "voided"]
        assert len(non_void) == 1
        assert non_void[0].order_id == o2

    @pytest.mark.asyncio
    async def test_tip_report_matches_events(self, ledger):
        """Sum of TIP_ADJUSTED events matches per-payment tip totals."""
        _, _, _, _ = await self._seed_two_orders(ledger)
        events = await ledger.get_events_since(0, limit=50000)

        event_tips = sum(
            e.payload.get("tip_amount", 0.0)
            for e in events if e.event_type == EventType.TIP_ADJUSTED
        )
        assert event_tips == 12.40

    @pytest.mark.asyncio
    async def test_server_filter_only_returns_their_orders(self, ledger):
        """Filtering by server_id returns only that server's orders."""
        await self._seed_two_orders(ledger)
        # Add order for different server
        o3 = _oid()
        await _create_order(ledger, o3, server_id="srv-2", server_name="Bob")
        await _add_item(ledger, o3, "i7", "Pasta", 20.00)

        events = await ledger.get_events_since(0, limit=50000)
        orders = project_orders(events)
        alice_orders = [o for o in orders.values() if o.server_id == "srv-1"]
        bob_orders = [o for o in orders.values() if o.server_id == "srv-2"]
        assert len(alice_orders) == 2
        assert len(bob_orders) == 1

    @pytest.mark.asyncio
    async def test_batch_submitted_totals_match(self, ledger):
        """BATCH_SUBMITTED payload matches sum of closed orders."""
        o1, o2, order1, order2 = await self._seed_two_orders(ledger)
        total_sales = money_round(order1.total + order2.total)

        evt = batch_submitted(
            terminal_id=TERMINAL, order_count=2, total_amount=total_sales,
            cash_total=order1.total, card_total=order2.total,
            order_ids=[o1, o2],
        )
        await ledger.append(evt)
        events = await ledger.get_events_by_type(EventType.BATCH_SUBMITTED)
        assert len(events) == 1
        assert events[0].payload["total_amount"] == total_sales
        assert events[0].payload["cash_total"] == order1.total
        assert events[0].payload["card_total"] == order2.total

    @pytest.mark.asyncio
    async def test_day_closed_boundary(self, ledger):
        """Events after DAY_CLOSED not in previous day's query."""
        o1, o2, order1, order2 = await self._seed_two_orders(ledger)
        total = money_round(order1.total + order2.total)

        close_evt = day_closed(
            terminal_id=TERMINAL, date="2026-04-05",
            total_orders=2, total_sales=total, total_tips=12.40,
            cash_total=order1.total, card_total=order2.total,
            order_ids=[o1, o2], payment_count=2,
        )
        await ledger.append(close_evt)

        # New order after day close
        o3 = _oid()
        await _create_order(ledger, o3)
        await _add_item(ledger, o3, "i7", "Coffee", 5.00)

        boundary = await ledger.get_last_day_close_sequence()
        new_events = await ledger.get_events_since(boundary, limit=50000)
        new_orders = project_orders(new_events)
        assert len(new_orders) == 1
        assert o3 in new_orders

    @pytest.mark.asyncio
    async def test_cash_vs_card_breakdown(self, ledger):
        """cash_total + card_total = total confirmed payments."""
        _, _, order1, order2 = await self._seed_two_orders(ledger)
        events = await ledger.get_events_since(0, limit=50000)
        orders = project_orders(events)

        cash = Decimal("0")
        card = Decimal("0")
        for order in orders.values():
            for p in order.payments:
                if p.status == "confirmed":
                    if p.method == "cash":
                        cash += Decimal(str(p.amount))
                    else:
                        card += Decimal(str(p.amount))

        total_paid = float(cash + card)
        assert total_paid == money_round(order1.total + order2.total)

    @pytest.mark.asyncio
    async def test_discount_reduces_net_sales(self, ledger):
        """Discounts reduce net sales in aggregation."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Steak", 50.00)
        disc = create_event(
            event_type=EventType.DISCOUNT_APPROVED,
            terminal_id=TERMINAL,
            payload={"discount_type": "promo", "amount": 10.00,
                     "reason": "happy hour", "approved_by": "mgr"},
            correlation_id=oid,
        )
        await ledger.append(disc)
        order = await _get_order(ledger, oid)
        assert order.discount_total == 10.00
        # net = subtotal - discount = 50 - 10 = 40
        net = order.subtotal - order.discount_total
        assert net == 40.00


# ═══════════════════════════════════════════════════════════════════════════
# 6. OFFLINE / RESILIENCE
# ═══════════════════════════════════════════════════════════════════════════

class TestOfflineResilience:
    """WAL crash recovery, sync tracking, print queue durability."""

    @pytest.mark.asyncio
    async def test_committed_events_survive_reopen(self, tmp_path):
        """Events survive close-and-reopen (normal shutdown)."""
        db_path = str(tmp_path / "resilience.db")
        async with EventLedger(db_path) as ledger:
            oid = _oid()
            await _create_order(ledger, oid)
            await _add_item(ledger, oid, "i1", "Burger", 10.00)

        # Reopen
        async with EventLedger(db_path) as ledger:
            events = await ledger.get_events_by_correlation(oid)
            assert len(events) == 2
            order = _project(events)
            assert order.subtotal == 10.00

    @pytest.mark.asyncio
    async def test_hash_chain_valid_after_reopen(self, tmp_path):
        """Hash chain verifies after close/reopen."""
        db_path = str(tmp_path / "chain.db")
        async with EventLedger(db_path) as ledger:
            for i in range(10):
                oid = _oid()
                evt = order_created(terminal_id=TERMINAL, order_id=oid)
                evt = evt.model_copy(update={"correlation_id": oid})
                await ledger.append(evt)

        async with EventLedger(db_path) as ledger:
            is_valid, first_invalid = await ledger.verify_chain()
            assert is_valid

    @pytest.mark.asyncio
    async def test_event_sync_tracking(self, tmp_path):
        """mark_synced / get_unsynced correctly tracks sync state."""
        db_path = str(tmp_path / "sync.db")
        async with EventLedger(db_path) as ledger:
            oid = _oid()
            await _create_order(ledger, oid)
            await _add_item(ledger, oid, "i1", "Burger", 10.00)

            unsynced = await ledger.get_unsynced_events(limit=100)
            assert len(unsynced) == 2

            ids = [e.event_id for e in unsynced]
            await ledger.mark_synced(ids)

            unsynced = await ledger.get_unsynced_events(limit=100)
            assert len(unsynced) == 0

    @pytest.mark.asyncio
    async def test_print_queue_survives_restart(self, tmp_path):
        """Print queue jobs persist across close/reopen."""
        from app.printing.print_queue import PrintJobQueue

        db_path = str(tmp_path / "pq.db")
        queue = PrintJobQueue(db_path)
        await queue.connect()
        job_id = await queue.enqueue(
            order_id="o1", template_id="kitchen",
            printer_mac="AA:BB:CC", ticket_number="KT-001",
            context={"items": []},
        )
        await queue.close()

        # Reopen
        queue2 = PrintJobQueue(db_path)
        await queue2.connect()
        try:
            pending = await queue2.get_pending_jobs()
            assert len(pending) == 1
            assert pending[0]["job_id"] == job_id
        finally:
            await queue2.close()

    @pytest.mark.asyncio
    async def test_new_write_after_reopen_extends_chain(self, tmp_path):
        """Writing after reopen correctly extends the hash chain."""
        db_path = str(tmp_path / "extend.db")
        async with EventLedger(db_path) as ledger:
            oid = _oid()
            await _create_order(ledger, oid)

        async with EventLedger(db_path) as ledger:
            await _add_item(ledger, oid, "i1", "Burger", 10.00)
            is_valid, _ = await ledger.verify_chain()
            assert is_valid
            count = await ledger.count_events()
            assert count == 2


# ═══════════════════════════════════════════════════════════════════════════
# 7. USER FLOW AND PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestUserFlowPermissions:
    """Clock in/out, RBAC gaps, tip ceiling manager approval."""

    @pytest.mark.asyncio
    async def test_clock_in_creates_event(self, ledger):
        evt = user_logged_in(
            terminal_id=TERMINAL, employee_id="emp-1",
            employee_name="Alice",
        )
        await ledger.append(evt)
        events = await ledger.get_events_by_type(EventType.USER_LOGGED_IN)
        assert len(events) == 1
        assert events[0].payload["employee_id"] == "emp-1"

    @pytest.mark.asyncio
    async def test_clock_out_creates_event(self, ledger):
        await ledger.append(user_logged_in(
            terminal_id=TERMINAL, employee_id="emp-1",
            employee_name="Alice",
        ))
        await ledger.append(user_logged_out(
            terminal_id=TERMINAL, employee_id="emp-1",
            employee_name="Alice",
        ))
        logins = await ledger.get_events_by_type(EventType.USER_LOGGED_IN)
        logouts = await ledger.get_events_by_type(EventType.USER_LOGGED_OUT)
        assert len(logins) == 1
        assert len(logouts) == 1

    @pytest.mark.asyncio
    async def test_clocked_in_set_tracking(self, ledger):
        """Replay login/logout events to derive who is clocked in."""
        await ledger.append(user_logged_in(
            terminal_id=TERMINAL, employee_id="emp-1",
            employee_name="Alice",
        ))
        await ledger.append(user_logged_in(
            terminal_id=TERMINAL, employee_id="emp-2",
            employee_name="Bob",
        ))
        await ledger.append(user_logged_out(
            terminal_id=TERMINAL, employee_id="emp-1",
            employee_name="Alice",
        ))

        logins = await ledger.get_events_by_type(EventType.USER_LOGGED_IN)
        logouts = await ledger.get_events_by_type(EventType.USER_LOGGED_OUT)
        clocked_in = {}
        for e in sorted(logins, key=lambda x: x.sequence_number or 0):
            clocked_in[e.payload["employee_id"]] = e
        for e in sorted(logouts, key=lambda x: x.sequence_number or 0):
            clocked_in.pop(e.payload["employee_id"], None)

        assert "emp-2" in clocked_in
        assert "emp-1" not in clocked_in

    @pytest.mark.asyncio
    async def test_tip_ceiling_manager_approval_required(self, ledger):
        """$200 tip on $100 sale (200%) → NEEDS_APPROVAL."""
        from app.core.adapters.payment_validator import PaymentValidator
        from app.core.adapters.base_payment import TransactionRequest, ValidationStatus

        validator = PaymentValidator(ledger)
        req = TransactionRequest(
            terminal_id=TERMINAL, order_id="o1",
            amount=Decimal("100.00"),
            tip_amount=Decimal("200.00"),
        )
        result = await validator.validate(req, device=None)
        assert result.status == ValidationStatus.NEEDS_APPROVAL

    @pytest.mark.asyncio
    async def test_void_approved_by_recorded_in_payload(self, ledger):
        """When approved_by is provided, it is recorded in the event."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)
        evt = order_voided(
            terminal_id=TERMINAL, order_id=oid,
            reason="mistake", approved_by="mgr-42",
        )
        await ledger.append(evt)
        events = await ledger.get_events_by_correlation(oid)
        void_evts = [e for e in events if e.event_type == EventType.ORDER_VOIDED]
        assert len(void_evts) == 1
        assert void_evts[0].payload["approved_by"] == "mgr-42"

    @pytest.mark.asyncio
    async def test_void_api_enforces_manager_approval(self, ledger):
        """Void API route now enforces approved_by — returns 403 without it."""
        from fastapi import HTTPException
        from app.api.routes.orders import void_order, VoidOrderRequest

        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00)

        # Empty string rejected
        with pytest.raises(HTTPException) as exc_info:
            req = VoidOrderRequest(reason="test", approved_by="   ")
            await void_order(oid, req, ledger)
        assert exc_info.value.status_code == 403

        # With valid manager ID it works
        req = VoidOrderRequest(reason="test", approved_by="mgr-1")
        result = await void_order(oid, req, ledger)
        assert result.status == "voided"
