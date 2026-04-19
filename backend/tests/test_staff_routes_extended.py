"""
Extended Staff Route Tests
==========================
Covers endpoints not in test_api_routes.py:
    - declare_cash_tips
    - get_clocked_in (empty, after clock-in, after clock-out)
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from app.core.event_ledger import EventLedger
from app.api import dependencies as deps

TEST_DB = Path("./data/test_staff_ext.db")


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


# ─── Tests ──────────────────────────────────────────────────────────────────

async def test_declare_cash_tips(client):
    """POST /api/v1/servers/declare-cash-tips records cash tips."""
    resp = await client.post("/api/v1/servers/declare-cash-tips", json={
        "server_id": "srv-01",
        "amount": 50.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["server_id"] == "srv-01"
    assert data["amount"] == 50.0


async def test_get_clocked_in_empty(client):
    """GET /api/v1/servers/clocked-in on empty ledger returns empty list."""
    resp = await client.get("/api/v1/servers/clocked-in")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["staff"], list)
    assert len(data["staff"]) == 0


async def test_clocked_in_after_clock_in(client):
    """After clock-in, get_clocked_in includes the server."""
    await client.post("/api/v1/servers/clock-in", json={
        "employee_id": "emp-01",
        "employee_name": "Alice",
    })

    resp = await client.get("/api/v1/servers/clocked-in")
    assert resp.status_code == 200
    staff = resp.json()["staff"]
    assert len(staff) == 1
    assert staff[0]["employee_id"] == "emp-01"
    assert staff[0]["employee_name"] == "Alice"


async def test_clocked_in_after_clock_out(client):
    """After clock-in then clock-out, get_clocked_in returns empty."""
    await client.post("/api/v1/servers/clock-in", json={
        "employee_id": "emp-02",
        "employee_name": "Bob",
    })

    await client.post("/api/v1/servers/clock-out", json={
        "employee_id": "emp-02",
        "employee_name": "Bob",
    })

    resp = await client.get("/api/v1/servers/clocked-in")
    assert resp.status_code == 200
    staff = resp.json()["staff"]
    assert len(staff) == 0
