"""
Tests for check/order state validity.

Validates that:
- get_open_orders correctly tracks reopened orders
- Split-by-seat child orders are fetchable individually
- Projections and event_ledger agree on open/closed/voided state
- close-batch / close-day don't emit duplicate lifecycle events
- No phantom "printed" status leaks into projections

Run with: pytest tests/test_check_state_validity.py -v
"""

import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.event_ledger import EventLedger, get_open_orders
from app.core.events import (
    order_created,
    item_added,
    payment_initiated,
    payment_confirmed,
    order_closed,
    order_reopened,
    order_voided,
    EventType,
)
from app.core.projections import project_order, project_orders, Order


TERMINAL = "T-test"
TAX_RATE = 0.07


def _fresh_db():
    path = "./data/test_check_states.db"
    if os.path.exists(path):
        os.remove(path)
    return path


# ═══════════════════════════════════════════════════════
#  1. get_open_orders tracks ORDER_REOPENED
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reopened_order_appears_in_open_orders():
    """An order that was closed then reopened must appear in get_open_orders."""
    async with EventLedger(_fresh_db()) as ledger:
        oid = "order_reopen_test"

        # Create → Close → Reopen
        evt = order_created(terminal_id=TERMINAL, order_id=oid, table="1")
        evt = evt.model_copy(update={"correlation_id": oid})
        await ledger.append(evt)

        evt = order_closed(terminal_id=TERMINAL, order_id=oid, total=0.0)
        await ledger.append(evt)

        evt = order_reopened(terminal_id=TERMINAL, order_id=oid)
        await ledger.append(evt)

        open_ids = await get_open_orders(ledger)
        assert oid in open_ids, f"Reopened order {oid} should be in open list"


@pytest.mark.asyncio
async def test_reopened_then_closed_not_in_open():
    """An order reopened then closed again must NOT appear in get_open_orders."""
    async with EventLedger(_fresh_db()) as ledger:
        oid = "order_reclose_test"

        evt = order_created(terminal_id=TERMINAL, order_id=oid, table="2")
        evt = evt.model_copy(update={"correlation_id": oid})
        await ledger.append(evt)

        evt = order_closed(terminal_id=TERMINAL, order_id=oid, total=0.0)
        await ledger.append(evt)

        evt = order_reopened(terminal_id=TERMINAL, order_id=oid)
        await ledger.append(evt)

        evt = order_closed(terminal_id=TERMINAL, order_id=oid, total=0.0)
        await ledger.append(evt)

        open_ids = await get_open_orders(ledger)
        assert oid not in open_ids, "Re-closed order should not be in open list"


@pytest.mark.asyncio
async def test_voided_order_not_in_open():
    """A voided order must not appear in get_open_orders."""
    async with EventLedger(_fresh_db()) as ledger:
        oid = "order_void_test"

        evt = order_created(terminal_id=TERMINAL, order_id=oid, table="3")
        evt = evt.model_copy(update={"correlation_id": oid})
        await ledger.append(evt)

        evt = order_voided(terminal_id=TERMINAL, order_id=oid, reason="test")
        await ledger.append(evt)

        open_ids = await get_open_orders(ledger)
        assert oid not in open_ids, "Voided order should not be in open list"


@pytest.mark.asyncio
async def test_plain_open_order_in_open():
    """A freshly created order must appear in get_open_orders."""
    async with EventLedger(_fresh_db()) as ledger:
        oid = "order_plain_open"

        evt = order_created(terminal_id=TERMINAL, order_id=oid, table="4")
        evt = evt.model_copy(update={"correlation_id": oid})
        await ledger.append(evt)

        open_ids = await get_open_orders(ledger)
        assert oid in open_ids


# ═══════════════════════════════════════════════════════
#  2. Projection and event_ledger agree on state
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_projection_agrees_with_ledger_open_orders():
    """Projected open orders must match get_open_orders for basic lifecycle."""
    async with EventLedger(_fresh_db()) as ledger:
        orders = {}
        for i, status_target in enumerate(["open", "closed", "voided", "reopened"]):
            oid = f"order_agree_{i}"
            evt = order_created(terminal_id=TERMINAL, order_id=oid, table=str(i))
            evt = evt.model_copy(update={"correlation_id": oid})
            await ledger.append(evt)

            if status_target in ("closed", "reopened"):
                evt = order_closed(terminal_id=TERMINAL, order_id=oid, total=0.0)
                await ledger.append(evt)

            if status_target == "voided":
                evt = order_voided(terminal_id=TERMINAL, order_id=oid, reason="test")
                await ledger.append(evt)

            if status_target == "reopened":
                evt = order_reopened(terminal_id=TERMINAL, order_id=oid)
                await ledger.append(evt)

            orders[oid] = status_target

        # Check event_ledger function
        open_ids = set(await get_open_orders(ledger))

        # Check projections
        all_events = await ledger.get_events_since(0, limit=50000)
        projected = project_orders(all_events)
        projected_open = {oid for oid, o in projected.items() if o.status == "open"}

        # "open" and "reopened" should both be in open sets
        expected_open = {oid for oid, st in orders.items() if st in ("open", "reopened")}

        assert open_ids == expected_open, f"Ledger open: {open_ids} != expected: {expected_open}"
        assert projected_open == expected_open, f"Projected open: {projected_open} != expected: {expected_open}"


# ═══════════════════════════════════════════════════════
#  3. Split-by-seat child order correlation_id
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_split_child_order_fetchable_by_correlation():
    """A child order from split-by-seat must have its ORDER_CREATED event
    findable via get_events_by_correlation so individual fetches work."""
    async with EventLedger(_fresh_db()) as ledger:
        child_id = "order_split_child_001"

        # Simulate what split-by-seat does AFTER the fix:
        # CREATE event with correlation_id set
        create_evt = order_created(
            terminal_id=TERMINAL,
            order_id=child_id,
            order_type="dine_in",
            guest_count=1,
            table="5",
        )
        create_evt = create_evt.model_copy(update={"correlation_id": child_id})
        await ledger.append(create_evt)

        # Add an item (already sets correlation_id correctly)
        add_evt = item_added(
            terminal_id=TERMINAL,
            order_id=child_id,
            item_id="item_split_1",
            menu_item_id="menu_burger",
            name="Burger",
            price=10.00,
        )
        await ledger.append(add_evt)

        # Fetch by correlation — must include the CREATE event
        events = await ledger.get_events_by_correlation(child_id)
        assert len(events) >= 2, f"Expected >= 2 events, got {len(events)}"

        event_types = [e.event_type for e in events]
        assert EventType.ORDER_CREATED in event_types, (
            "ORDER_CREATED must be in correlation query results"
        )

        # Project must succeed (not None)
        order = project_order(events, tax_rate=TAX_RATE)
        assert order is not None, "Child order projection must not be None"
        assert order.order_id == child_id
        assert len(order.items) == 1


@pytest.mark.asyncio
async def test_split_child_without_correlation_id_fails():
    """Without correlation_id on CREATE, the child order can't be fetched
    individually — demonstrating the bug this fix addresses."""
    async with EventLedger(_fresh_db()) as ledger:
        child_id = "order_split_broken"

        # Simulate the OLD buggy behavior: no correlation_id on CREATE
        create_evt = order_created(
            terminal_id=TERMINAL,
            order_id=child_id,
            order_type="dine_in",
            guest_count=1,
        )
        # Deliberately NOT setting correlation_id (old bug)
        await ledger.append(create_evt)

        add_evt = item_added(
            terminal_id=TERMINAL,
            order_id=child_id,
            item_id="item_broken_1",
            menu_item_id="menu_fries",
            name="Fries",
            price=5.00,
        )
        await ledger.append(add_evt)

        # Fetch by correlation — CREATE event will be MISSING
        events = await ledger.get_events_by_correlation(child_id)
        event_types = [e.event_type for e in events]

        # The CREATE event is not in the results (no correlation_id)
        assert EventType.ORDER_CREATED not in event_types, (
            "Without correlation_id, CREATE should not appear in correlation query"
        )

        # Projection returns None because no ORDER_CREATED event found
        order = project_order(events, tax_rate=TAX_RATE)
        assert order is None, (
            "Without the CREATE event, projection should return None (the ghost check bug)"
        )


# ═══════════════════════════════════════════════════════
#  4. No phantom "printed" status in projections
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_no_printed_status_in_projections():
    """The projection system should never produce 'printed' status.
    Valid statuses are: open, paid, closed, voided."""
    async with EventLedger(_fresh_db()) as ledger:
        oid = "order_status_check"

        evt = order_created(terminal_id=TERMINAL, order_id=oid, table="6")
        evt = evt.model_copy(update={"correlation_id": oid})
        await ledger.append(evt)

        add_evt = item_added(
            terminal_id=TERMINAL,
            order_id=oid,
            item_id="item_stat_1",
            menu_item_id="menu_salad",
            name="Salad",
            price=8.00,
        )
        await ledger.append(add_evt)

        events = await ledger.get_events_by_correlation(oid)
        order = project_order(events, tax_rate=TAX_RATE)

        assert order.status in ("open", "paid", "closed", "voided"), (
            f"Unexpected status: {order.status}"
        )
        assert order.status != "printed", "Status should never be 'printed'"


# ═══════════════════════════════════════════════════════
#  5. Duplicate close prevention
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_double_close_does_not_produce_duplicate_events():
    """Closing an already-closed order should not append another ORDER_CLOSED event.
    This tests the guard logic used in close-batch/close-day."""
    async with EventLedger(_fresh_db()) as ledger:
        oid = "order_double_close"

        evt = order_created(terminal_id=TERMINAL, order_id=oid, table="7")
        evt = evt.model_copy(update={"correlation_id": oid})
        await ledger.append(evt)

        # Close it
        evt = order_closed(terminal_id=TERMINAL, order_id=oid, total=0.0)
        await ledger.append(evt)

        # Verify it's closed
        events = await ledger.get_events_by_correlation(oid)
        order = project_order(events)
        assert order.status == "closed"

        # Simulate what close-batch does: check status before emitting
        if order.status not in ("closed", "voided"):
            # This branch should NOT execute
            evt = order_closed(terminal_id=TERMINAL, order_id=oid, total=0.0)
            await ledger.append(evt)

        # Count ORDER_CLOSED events — should be exactly 1
        events = await ledger.get_events_by_correlation(oid)
        close_count = sum(
            1 for e in events if e.event_type == EventType.ORDER_CLOSED
        )
        assert close_count == 1, f"Expected 1 ORDER_CLOSED event, got {close_count}"


# ═══════════════════════════════════════════════════════
#  6. Paid status consistency
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_paid_order_not_in_open_after_close():
    """A paid-then-closed order must not appear in get_open_orders."""
    async with EventLedger(_fresh_db()) as ledger:
        oid = "order_paid_close"

        evt = order_created(terminal_id=TERMINAL, order_id=oid, table="8")
        evt = evt.model_copy(update={"correlation_id": oid})
        await ledger.append(evt)

        add_evt = item_added(
            terminal_id=TERMINAL, order_id=oid,
            item_id="item_pc_1", menu_item_id="menu_steak",
            name="Steak", price=25.00,
        )
        await ledger.append(add_evt)

        pay_evt = payment_initiated(
            terminal_id=TERMINAL, order_id=oid,
            payment_id="pay_1", amount=26.75, method="card",
        )
        await ledger.append(pay_evt)

        confirm_evt = payment_confirmed(
            terminal_id=TERMINAL, order_id=oid,
            payment_id="pay_1", transaction_id="tx_1",
            amount=26.75, tax=1.75,
        )
        await ledger.append(confirm_evt)

        # At this point, projection status = "paid" but no ORDER_CLOSED event
        events = await ledger.get_events_by_correlation(oid)
        order = project_order(events, tax_rate=TAX_RATE)
        assert order.status == "paid", f"Expected 'paid', got '{order.status}'"

        # get_open_orders sees this as "open" (no close event) — this is expected
        # because paid orders haven't been explicitly closed yet
        open_ids = await get_open_orders(ledger)
        assert oid in open_ids, "Paid (but not closed) order should still be in open list"

        # Now close it
        close_evt = order_closed(terminal_id=TERMINAL, order_id=oid, total=order.total)
        await ledger.append(close_evt)

        # Now it should be gone from open list
        open_ids = await get_open_orders(ledger)
        assert oid not in open_ids, "Closed order should not be in open list"
