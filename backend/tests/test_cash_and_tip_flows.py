import pytest
from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    order_created,
    item_added,
    item_sent,
)
from app.api.routes.payment_routes import (
    process_cash_payment,
    adjust_tip,
    CashPaymentRequest,
    TipAdjustRequest,
)
from app.core.projections import project_order
from app.config import settings
import uuid
import os

# Test database path
TEST_DB = "./data/test_cash_and_tip_flows.db"

# Use the configured tax rate from settings for consistent calculations
TEST_TAX_RATE = 0.07

@pytest.fixture
async def ledger(monkeypatch):
    # Set a fixed tax rate for these tests (process_cash_payment reads from settings)
    monkeypatch.setattr(settings, 'tax_rate', TEST_TAX_RATE)
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    async with EventLedger(TEST_DB) as _ledger:
        yield _ledger
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

async def create_simple_order(ledger, terminal_id, order_id, amount):
    # 1. ORDER_CREATED
    evt = order_created(terminal_id=terminal_id, order_id=order_id, correlation_id=order_id)
    await ledger.append(evt)
    # 2. ITEM_ADDED
    evt = item_added(
        terminal_id=terminal_id,
        order_id=order_id,
        item_id=str(uuid.uuid4()),
        menu_item_id="item-01",
        name="Test Burger",
        price=amount
    )
    await ledger.append(evt)
    # 3. ITEM_SENT (to finalize the order for payment)
    evt = item_sent(
        terminal_id=terminal_id,
        order_id=order_id,
        item_id=evt.payload["item_id"],
        name="Test Burger"
    )
    await ledger.append(evt)

@pytest.mark.asyncio
async def test_cash_payment_success(ledger):
    """Verify that a cash payment emits payment.initiated and payment.confirmed events."""
    terminal_id = "T-01"
    order_id = "order-cash-01"
    amount = 25.50
    
    await create_simple_order(ledger, terminal_id, order_id, amount)
    
    request = CashPaymentRequest(order_id=order_id, amount=amount)
    response = await process_cash_payment(request, ledger)
    
    assert response["success"] is True
    
    events = await ledger.get_events_by_correlation(order_id)
    
    # Check for payment events
    # We use string literals for these because we're testing the system at the API level
    initiated = [e for e in events if e.event_type == EventType.PAYMENT_INITIATED]
    confirmed = [e for e in events if e.event_type == EventType.PAYMENT_CONFIRMED]
    
    assert len(initiated) == 1
    assert len(confirmed) == 1
    assert initiated[0].payload["amount"] == 25.50
    assert confirmed[0].payload["amount"] == 25.50
    
    # Verify precision (2dp)
    assert f"{initiated[0].payload['amount']:.2f}" == "25.50"
    assert f"{confirmed[0].payload['amount']:.2f}" == "25.50"

@pytest.mark.asyncio
async def test_cash_payment_with_tip(ledger):
    """Verify that including a tip in the cash payment emits a TIP_ADJUSTED event."""
    terminal_id = "T-01"
    order_id = "order-cash-tip-01"
    amount = 20.00
    tip = 5.00
    
    await create_simple_order(ledger, terminal_id, order_id, amount)
    
    request = CashPaymentRequest(order_id=order_id, amount=amount, tip=tip)
    response = await process_cash_payment(request, ledger)
    
    assert response["success"] is True
    
    events = await ledger.get_events_by_correlation(order_id)
    
    # Check for tip adjusted event
    tips = [e for e in events if e.event_type == EventType.TIP_ADJUSTED]
    assert len(tips) == 1
    assert tips[0].payload["tip_amount"] == 5.00
    assert tips[0].payload["payment_id"] == response["payment_id"]
    
    # Verify initiated amount is sale only (tip tracked separately via TIP_ADJUSTED)
    initiated = [e for e in events if e.event_type == EventType.PAYMENT_INITIATED][0]
    assert initiated.payload["amount"] == 20.00

@pytest.mark.asyncio
async def test_cash_payment_auto_closes_order(ledger):
    """Verify that the order status transitions to 'closed' when fully paid via cash."""
    terminal_id = "T-01"
    order_id = "order-auto-close-01"
    amount = 15.00
    
    await create_simple_order(ledger, terminal_id, order_id, amount)
    
    # Check that it's open
    events = await ledger.get_events_by_correlation(order_id)
    order = project_order(events, tax_rate=TEST_TAX_RATE)
    assert order.status == "open"
    assert order.total == 16.05 # 15.00 * 1.07

    # Pay EXACT total (including tax)
    request = CashPaymentRequest(order_id=order_id, amount=16.05)
    await process_cash_payment(request, ledger)
    
    events = await ledger.get_events_by_correlation(order_id)
    order = project_order(events, tax_rate=TEST_TAX_RATE)
    
    # In project_order: 
    # PAYMENT_CONFIRMED -> if order.is_fully_paid: order.status = "paid"
    # In process_cash_payment route:
    # if order and order.is_fully_paid: append(order_closed)
    # Re-projected after order_closed -> status = "closed"
    
    assert order.status == "closed"
    
    # Check for ORDER_CLOSED event
    closed_evts = [e for e in events if e.event_type == EventType.ORDER_CLOSED]
    assert len(closed_evts) == 1
    assert closed_evts[0].payload["total"] == 16.05

@pytest.mark.asyncio
async def test_tip_adjustment_success(ledger):
    """Verify that adjusting a tip on a confirmed payment emits a TIP_ADJUSTED event."""
    terminal_id = "T-01"
    order_id = "order-tip-adj-01"
    amount = 50.00
    
    await create_simple_order(ledger, terminal_id, order_id, amount)
    
    # Initial cash payment (no tip)
    cash_req = CashPaymentRequest(order_id=order_id, amount=amount)
    cash_resp = await process_cash_payment(cash_req, ledger)
    payment_id = cash_resp["payment_id"]
    
    # Adjust tip
    tip_amount = 12.50
    adj_req = TipAdjustRequest(order_id=order_id, payment_id=payment_id, tip_amount=tip_amount)
    adj_resp = await adjust_tip(adj_req, ledger)
    
    assert adj_resp["success"] is True
    assert adj_resp["tip_amount"] == 12.50
    assert adj_resp["previous_tip"] == 0.0
    
    events = await ledger.get_events_by_correlation(order_id)
    tips = [e for e in events if e.event_type == EventType.TIP_ADJUSTED]
    # One from process_cash_payment (if tip > 0, but here it was 0, so should be 1 from adjust_tip)
    assert len(tips) == 1
    assert tips[0].payload["tip_amount"] == 12.50
    assert tips[0].payload["previous_tip"] == 0.0

@pytest.mark.asyncio
async def test_tip_adjustment_cumulative(ledger):
    """Verify that the previous tip amount is correctly captured in the event payload."""
    terminal_id = "T-01"
    order_id = "order-tip-cum-01"
    amount = 50.00
    
    await create_simple_order(ledger, terminal_id, order_id, amount)
    
    # Initial cash payment (no tip)
    cash_req = CashPaymentRequest(order_id=order_id, amount=amount)
    cash_resp = await process_cash_payment(cash_req, ledger)
    payment_id = cash_resp["payment_id"]
    
    # Adjust tip first time
    await adjust_tip(TipAdjustRequest(order_id=order_id, payment_id=payment_id, tip_amount=5.00), ledger)
    
    # Adjust tip second time
    adj_resp = await adjust_tip(TipAdjustRequest(order_id=order_id, payment_id=payment_id, tip_amount=7.50), ledger)
    
    assert adj_resp["success"] is True
    assert adj_resp["tip_amount"] == 7.50
    assert adj_resp["previous_tip"] == 5.00
    
    events = await ledger.get_events_by_correlation(order_id)
    tips = [e for e in events if e.event_type == EventType.TIP_ADJUSTED]
    assert len(tips) == 2
    assert tips[1].payload["previous_tip"] == 5.00

@pytest.mark.asyncio
async def test_tip_adjustment_failures(ledger):
    """Verify failure cases (e.g., non-existent order, non-confirmed payment)."""
    from fastapi import HTTPException
    
    # 1. Non-existent order
    with pytest.raises(HTTPException) as excinfo:
        await adjust_tip(TipAdjustRequest(order_id="no-order", payment_id="p1", tip_amount=5.0), ledger)
    assert excinfo.value.status_code == 404
    
    # 2. Non-existent payment
    terminal_id = "T-01"
    order_id = "order-fail-01"
    await create_simple_order(ledger, terminal_id, order_id, 10.00)
    with pytest.raises(HTTPException) as excinfo:
        await adjust_tip(TipAdjustRequest(order_id=order_id, payment_id="p-none", tip_amount=5.0), ledger)
    assert excinfo.value.status_code == 404

@pytest.mark.asyncio
async def test_precision_gate_2dp(ledger):
    """Precision gate rejects non-2dp monetary values at the ledger level."""
    terminal_id = "T-01"
    order_id = "order-precision-01"

    # Non-2dp price must be rejected by the precision gate
    amount = 10.3333333
    import pytest as _pt

    with _pt.raises(ValueError, match="non-2dp monetary values"):
        await create_simple_order(ledger, terminal_id, order_id, amount)

    # Properly rounded values should succeed
    order_id2 = "order-precision-02"
    await create_simple_order(ledger, terminal_id, order_id2, 10.33)

    request = CashPaymentRequest(order_id=order_id2, amount=10.33, tip=2.67)
    response = await process_cash_payment(request, ledger)
    assert response["amount"] == 10.33

    events = await ledger.get_events_by_correlation(order_id2)
    tip_evts = [e for e in events if e.event_type == EventType.TIP_ADJUSTED]
    assert tip_evts[0].payload["tip_amount"] == 2.67

    init_evts = [e for e in events if e.event_type == EventType.PAYMENT_INITIATED]
    assert init_evts[0].payload["amount"] == 10.33
