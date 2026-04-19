"""
Extended Order API Route Tests
==============================
Covers endpoints not tested by test_api_routes.py:
    - list_active_orders
    - list_open_orders
    - reopen_order
    - close_batch
    - get_day_history
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from app.core.event_ledger import EventLedger
from app.core.events import EventType, create_event
from app.api import dependencies as deps

TEST_DB = Path("./data/test_api_orders_ext.db")


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        os.remove(TEST_DB)
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def client(ledger):
    from app.main import app

    async def _override_ledger():
        return ledger

    app.dependency_overrides[deps.get_ledger] = _override_ledger
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ─── Helpers ────────────────────────────────────────────────────────────────

async def create_order(client, table="T-1"):
    """Create and return an open order's ID."""
    resp = await client.post("/api/v1/orders", json={
        "table": table,
        "server_id": "srv-01",
        "server_name": "Test",
        "order_type": "dine_in",
        "guest_count": 1,
    })
    assert resp.status_code == 201
    return resp.json()["order_id"]


async def create_and_pay_order(client, table="T-1"):
    """Create order, add item, send, pay with cash, and return order_id."""
    order_id = await create_order(client, table)

    # Add item
    resp = await client.post(f"/api/v1/orders/{order_id}/items", json={
        "menu_item_id": "item-01",
        "name": "Burger",
        "price": 10.00,
        "quantity": 1,
        "category": "Entrees",
    })
    assert resp.status_code == 200

    # Send to kitchen
    resp = await client.post(f"/api/v1/orders/{order_id}/send")
    assert resp.status_code == 200

    # Cash pay — amount covers subtotal + tax
    resp = await client.post("/api/v1/payments/cash", json={
        "order_id": order_id,
        "amount": 10.70,
    })
    assert resp.status_code == 200

    return order_id


# ─── Tests ──────────────────────────────────────────────────────────────────

async def test_list_active_orders(client):
    """GET /api/v1/orders/active returns open orders."""
    await create_order(client, "A-1")
    await create_order(client, "A-2")

    resp = await client.get("/api/v1/orders/active")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


async def test_list_open_orders(client):
    """GET /api/v1/orders/open returns open orders."""
    await create_order(client, "B-1")

    resp = await client.get("/api/v1/orders/open")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    # All returned orders should be open
    for order in data:
        assert order["status"] == "open"


async def test_reopen_closed_order(client):
    """Paid+closed order can be reopened via POST /api/v1/orders/{id}/reopen.

    The cash payment endpoint auto-closes fully-paid orders, so the order
    is already closed after create_and_pay_order.
    """
    order_id = await create_and_pay_order(client, "C-1")

    # Verify the order is already closed (auto-closed by cash payment)
    resp = await client.get(f"/api/v1/orders/{order_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"

    # Reopen it
    resp = await client.post(f"/api/v1/orders/{order_id}/reopen")
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"


async def test_close_batch(client):
    """POST /api/v1/orders/close-batch settles paid orders."""
    await create_and_pay_order(client, "D-1")
    await create_and_pay_order(client, "D-2")

    resp = await client.post("/api/v1/orders/close-batch")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["order_count"] >= 2


# ─── Merge tests ────────────────────────────────────────────────────────────

async def _add_item(client, order_id, name="Burger", price=10.00):
    resp = await client.post(f"/api/v1/orders/{order_id}/items", json={
        "menu_item_id": "item-" + name.lower(),
        "name": name,
        "price": price,
        "quantity": 1,
        "category": "Entrees",
    })
    assert resp.status_code == 200


async def test_merge_orders_moves_items_and_voids_sources(client):
    target = await create_order(client, "M-1")
    source_a = await create_order(client, "M-2")
    source_b = await create_order(client, "M-3")

    await _add_item(client, target, "Burger", 10.00)
    await _add_item(client, source_a, "Fries", 4.00)
    await _add_item(client, source_b, "Soda", 3.00)

    resp = await client.post(f"/api/v1/orders/{target}/merge", json={
        "source_ids": [source_a, source_b],
        "approved_by": "mgr-01",
    })
    assert resp.status_code == 200
    merged = resp.json()
    item_names = sorted(i["name"] for i in merged["items"])
    assert item_names == ["Burger", "Fries", "Soda"]
    assert merged["status"] == "open"

    for sid in (source_a, source_b):
        resp = await client.get(f"/api/v1/orders/{sid}")
        assert resp.json()["status"] == "voided"


async def test_merge_requires_approved_by(client):
    target = await create_order(client, "M-4")
    source = await create_order(client, "M-5")
    resp = await client.post(f"/api/v1/orders/{target}/merge", json={
        "source_ids": [source],
    })
    assert resp.status_code == 403


async def test_merge_rejects_self(client):
    target = await create_order(client, "M-6")
    resp = await client.post(f"/api/v1/orders/{target}/merge", json={
        "source_ids": [target],
        "approved_by": "mgr-01",
    })
    assert resp.status_code == 400


async def test_merge_rejects_non_open_source(client):
    target = await create_order(client, "M-7")
    closed = await create_and_pay_order(client, "M-8")

    resp = await client.post(f"/api/v1/orders/{target}/merge", json={
        "source_ids": [closed],
        "approved_by": "mgr-01",
    })
    assert resp.status_code == 400


async def test_get_day_history(client):
    """After close-day, GET /api/v1/orders/day-history returns the summary."""
    await create_and_pay_order(client, "E-1")

    # Close day
    resp = await client.post("/api/v1/orders/close-day")
    assert resp.status_code == 200

    # Fetch history
    resp = await client.get("/api/v1/orders/day-history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Each entry should have a closed_at and date field
    assert "closed_at" in data[0]
