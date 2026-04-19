"""
KINDpos Daily Workflow Integration Test
=========================================
Walks through a complete day of service via the event ledger:

  1. Clock in
  2. Create order (take table)
  3. Add items
  4. Send to kitchen
  5. Cash payment → order auto-closes
  6. Create 2nd order
  7. Add items to 2nd order
  8. Card-style payment (initiate + confirm)
  9. Close 2nd order
  10. Tip adjustment on 2nd order
  11. Batch settle (close remaining)
  12. Clock out
  13. Close day
  14. Verify full event trail
"""

import pytest
import pytest_asyncio
import os
from pathlib import Path

from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    user_logged_in,
    user_logged_out,
    order_created,
    item_added,
    item_sent,
    payment_initiated,
    payment_confirmed,
    order_closed,
    tip_adjusted,
    batch_submitted,
    day_closed,
    create_event,
)
from app.core.projections import project_order, project_orders

TEST_DB = Path("./data/test_daily_workflow.db")
TERMINAL = "terminal_test"


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        os.remove(TEST_DB)
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        os.remove(TEST_DB)


@pytest.mark.asyncio
async def test_full_daily_workflow(ledger):
    """Walk through an entire day of service and verify every step."""

    # ─── 1. CLOCK IN ──────────────────────────────────────────────
    clock_in_evt = user_logged_in(
        terminal_id=TERMINAL,
        employee_id="emp_001",
        employee_name="Alice Server",
    )
    await ledger.append(clock_in_evt)

    events = await ledger.get_events_by_type(EventType.USER_LOGGED_IN)
    assert len(events) == 1
    assert events[0].payload["employee_id"] == "emp_001"

    # ─── 2. CREATE ORDER 1 (take table) ──────────────────────────
    order1_id = "order_test_001"
    evt = order_created(
        terminal_id=TERMINAL,
        order_id=order1_id,
        table="T1",
        server_id="emp_001",
        server_name="Alice Server",
        order_type="dine_in",
        guest_count=2,
    )
    evt = evt.model_copy(update={"correlation_id": order1_id})
    await ledger.append(evt)

    # ─── 3. ADD ITEMS TO ORDER 1 ─────────────────────────────────
    items_data = [
        ("item_001", "menu_steak", "NY Strip Steak", 45.00, "food"),
        ("item_002", "menu_wine", "Glass of Cabernet", 14.00, "wine"),
    ]
    for item_id, menu_id, name, price, category in items_data:
        evt = item_added(
            terminal_id=TERMINAL,
            order_id=order1_id,
            item_id=item_id,
            menu_item_id=menu_id,
            name=name,
            price=price,
            quantity=1,
            category=category,
        )
        await ledger.append(evt)

    # Verify order state
    order1_events = await ledger.get_events_by_correlation(order1_id)
    order1 = project_order(order1_events)
    assert order1 is not None
    assert len(order1.items) == 2
    assert order1.subtotal == 59.00
    assert order1.status == "open"

    # ─── 4. SEND TO KITCHEN ──────────────────────────────────────
    for item_id, _, name, _, category in items_data:
        evt = item_sent(
            terminal_id=TERMINAL,
            order_id=order1_id,
            item_id=item_id,
            name=name,
            category=category,
        )
        await ledger.append(evt)

    order1_events = await ledger.get_events_by_correlation(order1_id)
    order1 = project_order(order1_events)
    assert all(item.sent for item in order1.items)

    # ─── 5. CASH PAYMENT ON ORDER 1 ─────────────────────────────
    # Initiate + confirm (cash is immediate)
    pay1_id = "pay_cash_001"
    total1 = order1.total

    evt = payment_initiated(
        terminal_id=TERMINAL,
        order_id=order1_id,
        payment_id=pay1_id,
        amount=total1,
        method="cash",
    )
    await ledger.append(evt)

    evt = payment_confirmed(
        terminal_id=TERMINAL,
        order_id=order1_id,
        payment_id=pay1_id,
        transaction_id="cash_txn_001",
        amount=total1,
    )
    await ledger.append(evt)

    # Verify order is now "paid" (auto-status from projection)
    order1_events = await ledger.get_events_by_correlation(order1_id)
    order1 = project_order(order1_events)
    assert order1.status == "paid"
    assert order1.is_fully_paid
    assert order1.balance_due == 0

    # Close order 1
    evt = order_closed(
        terminal_id=TERMINAL,
        order_id=order1_id,
        total=order1.total,
    )
    await ledger.append(evt)

    order1_events = await ledger.get_events_by_correlation(order1_id)
    order1 = project_order(order1_events)
    assert order1.status == "closed"

    # ─── 6. CREATE ORDER 2 ───────────────────────────────────────
    order2_id = "order_test_002"
    evt = order_created(
        terminal_id=TERMINAL,
        order_id=order2_id,
        table="T3",
        server_id="emp_001",
        server_name="Alice Server",
        order_type="dine_in",
        guest_count=4,
    )
    evt = evt.model_copy(update={"correlation_id": order2_id})
    await ledger.append(evt)

    # ─── 7. ADD ITEMS TO ORDER 2 ─────────────────────────────────
    items2 = [
        ("item_003", "menu_burger", "Wagyu Burger", 28.00, "food"),
        ("item_004", "menu_salad", "Caesar Salad", 16.00, "food"),
        ("item_005", "menu_beer", "IPA Draft", 9.00, "beer"),
        ("item_006", "menu_beer", "IPA Draft", 9.00, "beer"),
    ]
    for item_id, menu_id, name, price, category in items2:
        evt = item_added(
            terminal_id=TERMINAL,
            order_id=order2_id,
            item_id=item_id,
            menu_item_id=menu_id,
            name=name,
            price=price,
            quantity=1,
            category=category,
        )
        await ledger.append(evt)

    order2_events = await ledger.get_events_by_correlation(order2_id)
    order2 = project_order(order2_events)
    assert len(order2.items) == 4
    assert order2.subtotal == 62.00

    # ─── 8. CARD PAYMENT (initiate + confirm) ────────────────────
    pay2_id = "pay_card_001"
    total2 = order2.total

    evt = payment_initiated(
        terminal_id=TERMINAL,
        order_id=order2_id,
        payment_id=pay2_id,
        amount=total2,
        method="card",
    )
    await ledger.append(evt)

    evt = payment_confirmed(
        terminal_id=TERMINAL,
        order_id=order2_id,
        payment_id=pay2_id,
        transaction_id="card_txn_002",
        amount=total2,
    )
    await ledger.append(evt)

    order2_events = await ledger.get_events_by_correlation(order2_id)
    order2 = project_order(order2_events)
    assert order2.status == "paid"
    assert order2.is_fully_paid

    # ─── 9. CLOSE ORDER 2 ────────────────────────────────────────
    evt = order_closed(
        terminal_id=TERMINAL,
        order_id=order2_id,
        total=order2.total,
    )
    await ledger.append(evt)

    order2_events = await ledger.get_events_by_correlation(order2_id)
    order2 = project_order(order2_events)
    assert order2.status == "closed"

    # ─── 10. TIP ADJUSTMENT on order 2 ───────────────────────────
    tip_evt = tip_adjusted(
        terminal_id=TERMINAL,
        order_id=order2_id,
        payment_id=pay2_id,
        tip_amount=12.40,
    )
    await ledger.append(tip_evt)

    # Verify tip is recorded in projection
    order2_events = await ledger.get_events_by_correlation(order2_id)
    order2 = project_order(order2_events)
    card_payment = [p for p in order2.payments if p.payment_id == pay2_id][0]
    assert card_payment.tip_amount == 12.40

    # ─── 11. BATCH SETTLE ────────────────────────────────────────
    # Compute totals for batch submission
    pre_close_events = await ledger.get_events_since(0, limit=50000)
    pre_close_orders = project_orders(pre_close_events)
    total_sales = sum(o.total for o in pre_close_orders.values() if o.status in ("closed", "paid"))

    submit_evt = batch_submitted(
        terminal_id=TERMINAL,
        order_count=2,
        total_amount=total_sales,
        cash_total=pre_close_orders[order1_id].total,
        card_total=pre_close_orders[order2_id].total,
        order_ids=[order1_id, order2_id],
    )
    await ledger.append(submit_evt)

    batch_events = await ledger.get_events_by_type(EventType.BATCH_SUBMITTED)
    assert len(batch_events) == 1
    assert batch_events[0].payload["order_count"] == 2
    assert batch_events[0].payload["total_amount"] == round(total_sales, 2)

    # ─── 12. CLOCK OUT ───────────────────────────────────────────
    clock_out_evt = user_logged_out(
        terminal_id=TERMINAL,
        employee_id="emp_001",
        employee_name="Alice Server",
    )
    await ledger.append(clock_out_evt)

    logout_events = await ledger.get_events_by_type(EventType.USER_LOGGED_OUT)
    assert len(logout_events) == 1

    # ─── 13. CLOSE DAY ─────────────────────────────────────────
    close_day_evt = day_closed(
        terminal_id=TERMINAL,
        date="2026-03-27",
        total_orders=2,
        total_sales=total_sales,
        total_tips=12.40,
        cash_total=pre_close_orders[order1_id].total,
        card_total=pre_close_orders[order2_id].total,
        order_ids=[order1_id, order2_id],
        payment_count=2,
    )
    await ledger.append(close_day_evt)

    # Verify DAY_CLOSED event is stored with full summary
    day_events = await ledger.get_events_by_type(EventType.DAY_CLOSED)
    assert len(day_events) == 1
    day_payload = day_events[0].payload
    assert day_payload["date"] == "2026-03-27"
    assert day_payload["total_orders"] == 2
    assert day_payload["total_sales"] == round(total_sales, 2)
    assert day_payload["total_tips"] == 12.40
    assert len(day_payload["order_ids"]) == 2
    assert day_payload["payment_count"] == 2
    assert "closed_at" in day_payload

    # ─── 14. VERIFY DAY BOUNDARY ───────────────────────────────
    # After DAY_CLOSED, the day boundary should be set
    boundary_seq = await ledger.get_last_day_close_sequence()
    assert boundary_seq > 0

    # Events after the boundary should be empty (no new orders)
    new_day_events = await ledger.get_events_since(boundary_seq, limit=50000)
    new_day_orders = project_orders(new_day_events)
    assert len(new_day_orders) == 0  # new day is clean

    # ─── 15. VERIFY FULL EVENT TRAIL ─────────────────────────────
    all_events = await ledger.get_events_since(0, limit=50000)
    all_orders = project_orders(all_events)

    # Both orders should be closed
    assert all(o.status == "closed" for o in all_orders.values())
    assert len(all_orders) == 2

    # Verify total event count (rough check)
    assert len(all_events) >= 18

    # Verify event type coverage
    event_types = {e.event_type for e in all_events}
    assert EventType.USER_LOGGED_IN in event_types
    assert EventType.USER_LOGGED_OUT in event_types
    assert EventType.ORDER_CREATED in event_types
    assert EventType.ITEM_ADDED in event_types
    assert EventType.ITEM_SENT in event_types
    assert EventType.PAYMENT_INITIATED in event_types
    assert EventType.PAYMENT_CONFIRMED in event_types
    assert EventType.ORDER_CLOSED in event_types
    assert EventType.TIP_ADJUSTED in event_types
    assert EventType.BATCH_SUBMITTED in event_types
    assert EventType.DAY_CLOSED in event_types

    # Verify sales totals
    assert total_sales > 0

    # Verify tips
    tip_events = [e for e in all_events if e.event_type == EventType.TIP_ADJUSTED]
    assert len(tip_events) == 1
    assert tip_events[0].payload["tip_amount"] == 12.40

    print(f"\n✓ Daily workflow complete:")
    print(f"  Orders: {len(all_orders)}")
    print(f"  Events: {len(all_events)}")
    print(f"  Sales: ${total_sales:.2f}")
    print(f"  Tips: $12.40")
    print(f"  Event types used: {len(event_types)}")
