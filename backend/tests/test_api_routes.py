"""
KINDpos API Route Integration Tests
====================================
Tests every API route handler through FastAPI's TestClient.

Coverage:
    1. Order routes — create, add items, send, close
    2. Payment routes — cash payment, tip adjust
    3. Config routes — terminal bundle, update config, 86/restore item
    4. Menu routes — categories, items
    5. Staff routes — clock in, clock out, roster
    6. Hardware routes — status, test-connection
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from app.config import settings
from app.core.event_ledger import EventLedger
from app.core.events import EventType, create_event
from app.api import dependencies as deps

# ─── Test database ──────────────────────────────────
TEST_DB = Path("./data/test_api_routes.db")


# ─── Fixtures ───────────────────────────────────────

@pytest_asyncio.fixture
async def ledger():
    """Fresh EventLedger per test."""
    if TEST_DB.exists():
        os.remove(TEST_DB)
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def client(ledger):
    """AsyncClient wired to the real FastAPI app with a test ledger."""
    # Import app here so module-level side effects don't fire early
    from app.main import app

    # Override the ledger dependency to use our test ledger
    async def _override_ledger():
        return ledger
    app.dependency_overrides[deps.get_ledger] = _override_ledger

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ═════════════════════════════════════════════════════
# 1. ORDER ROUTES
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_order(client):
    """POST /api/v1/orders — creates an order and returns 201."""
    resp = await client.post("/api/v1/orders", json={
        "table": "T-5",
        "server_id": "srv-01",
        "server_name": "Maria",
        "order_type": "dine_in",
        "guest_count": 2,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "open"
    assert data["table"] == "T-5"
    assert data["server_name"] == "Maria"
    assert data["guest_count"] == 2
    assert data["order_type"] == "dine_in"
    # Schema: financial fields present and zero
    assert data["subtotal"] == 0.0
    assert data["total"] == 0.0
    assert data["balance_due"] == 0.0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_get_order_not_found(client):
    """GET /api/v1/orders/{id} — 404 for nonexistent order."""
    resp = await client.get("/api/v1/orders/no-such-order")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_items_and_send(client, ledger):
    """POST items, then POST send — items marked sent, events written."""
    # Create order
    resp = await client.post("/api/v1/orders", json={
        "table": "T-1", "server_id": "srv-01", "server_name": "Maria",
    })
    oid = resp.json()["order_id"]

    # Add two items
    resp = await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "burger-01", "name": "Smash Burger",
        "price": 12.50, "quantity": 1, "category": "Mains",
    })
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["subtotal"] == 12.50

    resp = await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "fries-01", "name": "Waffle Fries",
        "price": 5.00, "quantity": 2, "category": "Sides",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    # 12.50 + 5.00*2 = 22.50
    assert data["subtotal"] == 22.50
    # Tax at 0.07: 22.50 * 0.07 = 1.575 -> 1.58
    assert data["tax"] == 1.58
    assert data["total"] == 24.08

    # Send to kitchen
    resp = await client.post(f"/api/v1/orders/{oid}/send")
    assert resp.status_code == 200
    send_data = resp.json()
    assert send_data["sent_count"] == 2

    # Verify ITEM_SENT events in ledger
    events = await ledger.get_events_by_type(EventType.ITEM_SENT)
    assert len(events) == 2

    # Second send should send nothing (all already sent)
    resp = await client.post(f"/api/v1/orders/{oid}/send")
    assert resp.json()["sent_count"] == 0


@pytest.mark.asyncio
async def test_full_order_lifecycle(client, ledger):
    """Create -> add item -> pay -> close — full happy path."""
    # Create
    resp = await client.post("/api/v1/orders", json={
        "table": "T-3", "server_id": "srv-01", "server_name": "Maria",
    })
    oid = resp.json()["order_id"]

    # Add item: $15.00
    resp = await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "rib-01", "name": "Ribeye",
        "price": 15.00, "quantity": 1,
    })
    total = resp.json()["total"]  # 15.00 + tax
    assert total == 16.05  # 15.00 * 1.07

    # Initiate payment
    resp = await client.post(f"/api/v1/orders/{oid}/payments", json={
        "amount": total, "method": "card",
    })
    assert resp.status_code == 200
    pay_id = resp.json()["payments"][0]["payment_id"]
    assert resp.json()["payments"][0]["status"] == "pending"

    # Confirm payment
    resp = await client.post(
        f"/api/v1/orders/{oid}/payments/{pay_id}/confirm",
        json={"transaction_id": "txn_abc123", "amount": total},
    )
    assert resp.status_code == 200
    assert resp.json()["amount_paid"] == total
    assert resp.json()["balance_due"] == 0.0

    # Close order
    resp = await client.post(f"/api/v1/orders/{oid}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"

    # Verify events in ledger
    events = await ledger.get_events_by_correlation(oid)
    types = [e.event_type for e in events]
    assert EventType.ORDER_CREATED in types
    assert EventType.ITEM_ADDED in types
    assert EventType.PAYMENT_INITIATED in types
    assert EventType.PAYMENT_CONFIRMED in types
    assert EventType.ORDER_CLOSED in types


@pytest.mark.asyncio
async def test_close_order_with_balance_fails(client):
    """Cannot close an order that has an unpaid balance."""
    resp = await client.post("/api/v1/orders", json={
        "table": "T-9", "server_id": "srv-01", "server_name": "Maria",
    })
    oid = resp.json()["order_id"]
    await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "item-1", "name": "Test Item", "price": 10.00,
    })
    resp = await client.post(f"/api/v1/orders/{oid}/close")
    assert resp.status_code == 400
    assert "balance due" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_void_order(client, ledger):
    """Voiding an order marks status 'voided' and writes event."""
    resp = await client.post("/api/v1/orders", json={
        "table": "T-7", "server_id": "srv-01", "server_name": "Maria",
    })
    oid = resp.json()["order_id"]
    resp = await client.post(f"/api/v1/orders/{oid}/void", json={
        "reason": "Customer left", "approved_by": "mgr-01",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "voided"

    events = await ledger.get_events_by_type(EventType.ORDER_VOIDED)
    assert len(events) == 1
    assert events[0].payload["reason"] == "Customer left"


@pytest.mark.asyncio
async def test_list_and_filter_orders(client):
    """GET /api/v1/orders with status filter."""
    # Create two orders
    await client.post("/api/v1/orders", json={"table": "T-1", "server_id": "s1", "server_name": "A"})
    resp2 = await client.post("/api/v1/orders", json={"table": "T-2", "server_id": "s2", "server_name": "B"})
    oid2 = resp2.json()["order_id"]
    await client.post(f"/api/v1/orders/{oid2}/void", json={"reason": "test", "approved_by": "mgr-1"})

    # All orders
    resp = await client.get("/api/v1/orders")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # Filter to open only
    resp = await client.get("/api/v1/orders?status_filter=open")
    assert len(resp.json()) == 1

    # Filter to voided
    resp = await client.get("/api/v1/orders?status_filter=voided")
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_remove_item(client):
    """DELETE item from order removes it from projection."""
    resp = await client.post("/api/v1/orders", json={"table": "T-1"})
    oid = resp.json()["order_id"]
    resp = await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "i1", "name": "Burger", "price": 10.00,
    })
    item_id = resp.json()["items"][0]["item_id"]

    resp = await client.delete(f"/api/v1/orders/{oid}/items/{item_id}")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 0


@pytest.mark.asyncio
async def test_modify_item(client):
    """PATCH item quantity updates subtotal."""
    resp = await client.post("/api/v1/orders", json={"table": "T-1"})
    oid = resp.json()["order_id"]
    resp = await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "i1", "name": "Burger", "price": 10.00, "quantity": 1,
    })
    item_id = resp.json()["items"][0]["item_id"]

    resp = await client.patch(f"/api/v1/orders/{oid}/items/{item_id}", json={
        "quantity": 3,
    })
    assert resp.status_code == 200
    assert resp.json()["items"][0]["quantity"] == 3
    assert resp.json()["subtotal"] == 30.00


@pytest.mark.asyncio
async def test_apply_modifier(client):
    """POST modifier adds to item and adjusts subtotal."""
    resp = await client.post("/api/v1/orders", json={"table": "T-1"})
    oid = resp.json()["order_id"]
    resp = await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "i1", "name": "Burger", "price": 10.00,
    })
    item_id = resp.json()["items"][0]["item_id"]

    resp = await client.post(f"/api/v1/orders/{oid}/items/{item_id}/modifiers", json={
        "modifier_id": "mod-bacon", "modifier_name": "Bacon",
        "modifier_price": 2.00, "action": "add",
    })
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert len(item["modifiers"]) == 1
    assert item["subtotal"] == 12.00  # 10.00 + 2.00


# ═════════════════════════════════════════════════════
# 2. PAYMENT ROUTES (cash flow + tip adjust)
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cash_payment_route(client, ledger):
    """POST /api/v1/payments/cash — processes cash and closes order."""
    # Create and populate order
    resp = await client.post("/api/v1/orders", json={
        "table": "T-1", "server_id": "srv-01", "server_name": "Maria",
    })
    oid = resp.json()["order_id"]
    await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "b1", "name": "Burger", "price": 20.00,
    })
    # Send to finalize
    await client.post(f"/api/v1/orders/{oid}/send")

    # total = 20.00 * 1.07 = 21.40
    resp = await client.post("/api/v1/payments/cash", json={
        "order_id": oid, "amount": 21.40,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["amount"] == 21.40

    # Verify events: PAYMENT_INITIATED + PAYMENT_CONFIRMED
    events = await ledger.get_events_by_correlation(oid)
    types = [e.event_type for e in events]
    assert EventType.PAYMENT_INITIATED in types
    assert EventType.PAYMENT_CONFIRMED in types

    # 2dp precision on financial payload
    init_evt = next(e for e in events if e.event_type == EventType.PAYMENT_INITIATED)
    assert f"{init_evt.payload['amount']:.2f}" == "21.40"


@pytest.mark.asyncio
async def test_cash_payment_with_tip(client, ledger):
    """Cash payment with tip emits TIP_ADJUSTED event."""
    resp = await client.post("/api/v1/orders", json={"table": "T-2"})
    oid = resp.json()["order_id"]
    await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "b1", "name": "Burger", "price": 10.00,
    })
    await client.post(f"/api/v1/orders/{oid}/send")

    resp = await client.post("/api/v1/payments/cash", json={
        "order_id": oid, "amount": 10.70, "tip": 3.00,
    })
    assert resp.status_code == 200
    assert resp.json()["tip"] == 3.00

    events = await ledger.get_events_by_correlation(oid)
    tip_evts = [e for e in events if e.event_type == EventType.TIP_ADJUSTED]
    assert len(tip_evts) == 1
    assert tip_evts[0].payload["tip_amount"] == 3.00


@pytest.mark.asyncio
async def test_tip_adjust_route(client, ledger):
    """POST /api/v1/payments/tip-adjust on confirmed payment."""
    resp = await client.post("/api/v1/orders", json={"table": "T-3"})
    oid = resp.json()["order_id"]
    await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "b1", "name": "Burger", "price": 10.00,
    })
    await client.post(f"/api/v1/orders/{oid}/send")

    # Pay cash (no tip initially)
    pay_resp = await client.post("/api/v1/payments/cash", json={
        "order_id": oid, "amount": 10.70,
    })
    pay_id = pay_resp.json()["payment_id"]

    # Adjust tip
    resp = await client.post("/api/v1/payments/tip-adjust", json={
        "order_id": oid, "payment_id": pay_id, "tip_amount": 5.50,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["tip_amount"] == 5.50
    assert data["previous_tip"] == 0.0


@pytest.mark.asyncio
async def test_tip_adjust_nonexistent_order(client):
    """Tip adjust on missing order returns 404."""
    resp = await client.post("/api/v1/payments/tip-adjust", json={
        "order_id": "no-order", "payment_id": "p1", "tip_amount": 5.00,
    })
    assert resp.status_code == 404


# ═════════════════════════════════════════════════════
# 3. CONFIG ROUTES
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_terminal_bundle(client):
    """GET /api/v1/config/terminal-bundle — returns full config bundle."""
    resp = await client.get("/api/v1/config/terminal-bundle")
    assert resp.status_code == 200
    data = resp.json()
    assert "store" in data
    assert "employees" in data
    assert "roles" in data
    assert "menu" in data
    assert "floor_plan" in data
    assert "hardware" in data
    assert data["bundle_version"] == 1


@pytest.mark.asyncio
async def test_update_store_info(client, ledger):
    """POST /api/v1/config/store/info — writes STORE_INFO_UPDATED event."""
    resp = await client.post("/api/v1/config/store/info", json={
        "restaurant_name": "Test Bistro",
        "address_line_1": "123 Main St",
        "city": "Springfield",
        "state": "IL",
        "zip": "62704",
        "phone": "555-0100",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    events = await ledger.get_events_by_type(EventType.STORE_INFO_UPDATED)
    assert len(events) == 1
    assert events[0].payload["restaurant_name"] == "Test Bistro"


@pytest.mark.asyncio
async def test_86_and_restore_menu_item(client, ledger):
    """POST 86 then restore — writes correct event types."""
    # 86 an item
    resp = await client.post("/api/v1/config/menu/86?item_id=burger-01")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    events = await ledger.get_events_by_type(EventType.MENU_ITEM_86D)
    assert len(events) == 1
    assert events[0].payload["item_id"] == "burger-01"

    # Restore it
    resp = await client.post("/api/v1/config/menu/restore?item_id=burger-01")
    assert resp.status_code == 200

    events = await ledger.get_events_by_type(EventType.MENU_ITEM_RESTORED)
    assert len(events) == 1
    assert events[0].payload["item_id"] == "burger-01"


@pytest.mark.asyncio
async def test_get_store_config(client):
    """GET /api/v1/config/store — returns projected config."""
    resp = await client.get("/api/v1/config/store")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_push_config_changes(client, ledger):
    """POST /api/v1/config/push — batch writes config events."""
    resp = await client.post("/api/v1/config/push", json=[
        {
            "event_type": "MENU_ITEM_CREATED",
            "payload": {
                "item_id": "new-item-01",
                "name": "Test Dish",
                "price": 9.99,
                "category": "Mains",
            },
        },
    ])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["events_written"] == 1

    events = await ledger.get_events_by_type(EventType.MENU_ITEM_CREATED)
    assert len(events) == 1
    assert events[0].payload["name"] == "Test Dish"


# ═════════════════════════════════════════════════════
# 4. MENU ROUTES
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_menu_empty(client):
    """GET /api/v1/menu — returns empty menu state on fresh ledger."""
    resp = await client.get("/api/v1/menu")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    assert "items" in data
    assert data["categories"] == []
    assert data["items"] == []


@pytest.mark.asyncio
async def test_get_categories_and_items(client, ledger):
    """Seed menu events, then verify /categories and /items return them."""
    # Seed a category
    cat_evt = create_event(
        event_type=EventType.MENU_CATEGORY_CREATED,
        terminal_id="OVERSEER",
        payload={
            "category_id": "cat-01",
            "name": "Mains",
            "label": "Mains",
            "color": "orange",
            "display_order": 1,
        },
    )
    await ledger.append(cat_evt)

    # Seed an item
    item_evt = create_event(
        event_type=EventType.MENU_ITEM_CREATED,
        terminal_id="OVERSEER",
        payload={
            "item_id": "item-01",
            "name": "Smash Burger",
            "price": 12.50,
            "category": "Mains",
        },
    )
    await ledger.append(item_evt)

    # Get categories
    resp = await client.get("/api/v1/menu/categories")
    assert resp.status_code == 200
    cats = resp.json()
    assert len(cats) == 1
    assert cats[0]["name"] == "Mains"

    # Get items
    resp = await client.get("/api/v1/menu/items")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "Smash Burger"
    assert items[0]["price"] == 12.50


# ═════════════════════════════════════════════════════
# 5. STAFF ROUTES
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_clock_in_and_out(client, ledger):
    """Clock in, verify clocked-in list, clock out, verify removed."""
    # Clock in
    resp = await client.post("/api/v1/servers/clock-in", json={
        "employee_id": "emp-01",
        "employee_name": "Maria",
        "pin": "1234",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["employee_id"] == "emp-01"
    assert "clocked_in_at" in data

    # Verify clocked-in list
    resp = await client.get("/api/v1/servers/clocked-in")
    assert resp.status_code == 200
    staff = resp.json()["staff"]
    assert len(staff) == 1
    assert staff[0]["employee_id"] == "emp-01"

    # Clock out
    resp = await client.post("/api/v1/servers/clock-out", json={
        "employee_id": "emp-01",
        "employee_name": "Maria",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify removed from clocked-in list
    resp = await client.get("/api/v1/servers/clocked-in")
    assert len(resp.json()["staff"]) == 0

    # Verify events
    logins = await ledger.get_events_by_type(EventType.USER_LOGGED_IN)
    logouts = await ledger.get_events_by_type(EventType.USER_LOGGED_OUT)
    assert len(logins) == 1
    assert len(logouts) == 1


@pytest.mark.asyncio
async def test_get_servers_roster(client):
    """GET /api/v1/servers — returns roster (empty on fresh ledger)."""
    resp = await client.get("/api/v1/servers")
    assert resp.status_code == 200
    assert "servers" in resp.json()


# ═════════════════════════════════════════════════════
# 6. HARDWARE ROUTES
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_hardware_status(client):
    """GET /api/v1/hardware/status — returns online status."""
    resp = await client.get("/api/v1/hardware/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert "default_subnet" in data
    assert "endpoints" in data


@pytest.mark.asyncio
async def test_hardware_test_connection(client):
    """POST /api/v1/hardware/test-connection — tests TCP connectivity."""
    # Test against a port that is almost certainly not open
    resp = await client.post("/api/v1/hardware/test-connection", json={
        "ip": "127.0.0.1",
        "port": 19999,
        "timeout": 0.5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ip"] == "127.0.0.1"
    assert data["port"] == 19999
    assert data["status"] in ("online", "unreachable")


# ═════════════════════════════════════════════════════
# 7. FINANCIAL PRECISION — 2dp on all monetary values
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_financial_2dp_precision(client, ledger):
    """All financial values in order response have 2dp precision."""
    resp = await client.post("/api/v1/orders", json={"table": "T-1"})
    oid = resp.json()["order_id"]

    # Add item with tricky price
    await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "i1", "name": "Special", "price": 9.99, "quantity": 3,
    })

    resp = await client.get(f"/api/v1/orders/{oid}")
    data = resp.json()

    # Subtotal: 9.99 * 3 = 29.97
    assert data["subtotal"] == 29.97
    # Tax: 29.97 * 0.07 = 2.0979 -> 2.10
    assert data["tax"] == 2.10
    # Total: 29.97 + 2.10 = 32.07
    assert data["total"] == 32.07

    # Verify 2dp in ledger event payloads
    events = await ledger.get_events_by_correlation(oid)
    item_evt = next(e for e in events if e.event_type == EventType.ITEM_ADDED)
    assert f"{item_evt.payload['price']:.2f}" == "9.99"


# ═════════════════════════════════════════════════════
# 8. DAY SUMMARY & CLOSE DAY
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_day_summary(client):
    """GET /api/v1/orders/day-summary — returns aggregates."""
    # Create and close an order
    resp = await client.post("/api/v1/orders", json={"table": "T-1"})
    oid = resp.json()["order_id"]
    await client.post(f"/api/v1/orders/{oid}/items", json={
        "menu_item_id": "b1", "name": "Burger", "price": 10.00,
    })
    await client.post(f"/api/v1/orders/{oid}/send")
    await client.post("/api/v1/payments/cash", json={
        "order_id": oid, "amount": 10.70,
    })

    resp = await client.get("/api/v1/orders/day-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["closed_orders"] >= 1
    assert data["total_sales"] > 0


@pytest.mark.asyncio
async def test_close_day(client, ledger):
    """POST /api/v1/orders/close-day — writes DAY_CLOSED event."""
    resp = await client.post("/api/v1/orders/close-day")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "summary" in data

    events = await ledger.get_events_by_type(EventType.DAY_CLOSED)
    assert len(events) == 1


# ═════════════════════════════════════════════════════
# 9. HEALTH CHECK
# ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_health_check(client):
    """GET /health — basic health endpoint."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["app"] == "KINDpos"
