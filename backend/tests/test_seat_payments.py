"""
KINDpos Seat-Level Payment Tests
=================================
Covers the seat_numbers tracking through payment events, projections,
and API responses.

Scenarios:
    1. Payment with seat_numbers stores them on the Payment projection
    2. Order.paid_seats aggregates seats from confirmed payments
    3. Partial seat payment leaves unpaid seats out of paid_seats
    4. Multiple seat payments accumulate in paid_seats
    5. Failed payment seats are NOT included in paid_seats
    6. Cash payment API route accepts and stores seat_numbers
    7. OrderResponse includes paid_seats from the backend
    8. Payment without seat_numbers still works (backwards compat)
"""

import os
import uuid

import pytest
import pytest_asyncio
from pathlib import Path

from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    order_created,
    item_added,
    payment_initiated,
    payment_confirmed,
    payment_failed,
    order_closed,
)
from app.core.projections import project_order, Order
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
    db_path = str(tmp_path / "test_seat_pay.db")
    async with EventLedger(db_path) as _ledger:
        yield _ledger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oid():
    return f"order_{uuid.uuid4().hex[:12]}"


def _pid():
    return f"pay_{uuid.uuid4().hex[:8]}"


async def _create_order(ledger, order_id):
    evt = order_created(
        terminal_id=TERMINAL, order_id=order_id,
        table="T1", server_id="srv-1", server_name="Alice",
        guest_count=2,
    )
    evt = evt.model_copy(update={"correlation_id": order_id})
    await ledger.append(evt)


async def _add_item(ledger, order_id, item_id, name, price, seat_number=None):
    evt = item_added(
        terminal_id=TERMINAL, order_id=order_id,
        item_id=item_id, menu_item_id=f"menu-{item_id}",
        name=name, price=price, quantity=1, category="food",
        seat_number=seat_number,
    )
    await ledger.append(evt)


async def _pay(ledger, order_id, payment_id, amount, seat_numbers=None, method="card"):
    init = payment_initiated(
        terminal_id=TERMINAL, order_id=order_id,
        payment_id=payment_id, amount=amount, method=method,
        seat_numbers=seat_numbers,
    )
    await ledger.append(init)
    conf = payment_confirmed(
        terminal_id=TERMINAL, order_id=order_id,
        payment_id=payment_id, transaction_id=f"txn_{payment_id}",
        amount=amount, seat_numbers=seat_numbers,
    )
    await ledger.append(conf)


async def _pay_initiated_only(ledger, order_id, payment_id, amount, seat_numbers=None):
    """Initiate but don't confirm (simulates pending/failed)."""
    init = payment_initiated(
        terminal_id=TERMINAL, order_id=order_id,
        payment_id=payment_id, amount=amount, method="card",
        seat_numbers=seat_numbers,
    )
    await ledger.append(init)


async def _fail_payment(ledger, order_id, payment_id, amount, seat_numbers=None):
    """Initiate then fail a payment."""
    init = payment_initiated(
        terminal_id=TERMINAL, order_id=order_id,
        payment_id=payment_id, amount=amount, method="card",
        seat_numbers=seat_numbers,
    )
    await ledger.append(init)
    fail = payment_failed(
        terminal_id=TERMINAL, order_id=order_id,
        payment_id=payment_id, error="Declined",
    )
    await ledger.append(fail)


async def _get_order(ledger, order_id):
    events = await ledger.get_events_by_correlation(order_id)
    return project_order(events, tax_rate=TAX_RATE)


# ═══════════════════════════════════════════════════════════════════════════
# 1. PROJECTION-LEVEL TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSeatPaymentProjection:
    """Verify seat_numbers flows through events → Payment → Order.paid_seats."""

    @pytest.mark.asyncio
    async def test_payment_stores_seat_numbers(self, ledger):
        """Confirmed payment with seat_numbers stores them on Payment."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00, seat_number=1)
        await _add_item(ledger, oid, "i2", "Fries", 5.00, seat_number=2)

        await _pay(ledger, oid, _pid(), 10.70, seat_numbers=[1])

        order = await _get_order(ledger, oid)
        assert len(order.payments) == 1
        assert order.payments[0].seat_numbers == [1]
        assert order.payments[0].status == "confirmed"

    @pytest.mark.asyncio
    async def test_paid_seats_single_seat(self, ledger):
        """Order.paid_seats returns just the confirmed payment's seats."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Steak", 25.00, seat_number=1)
        await _add_item(ledger, oid, "i2", "Salad", 8.00, seat_number=2)

        await _pay(ledger, oid, _pid(), 26.75, seat_numbers=[1])

        order = await _get_order(ledger, oid)
        assert order.paid_seats == [1]

    @pytest.mark.asyncio
    async def test_paid_seats_multiple_payments(self, ledger):
        """Two separate seat payments → paid_seats accumulates both."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Steak", 25.00, seat_number=1)
        await _add_item(ledger, oid, "i2", "Pasta", 15.00, seat_number=2)
        await _add_item(ledger, oid, "i3", "Wine", 12.00, seat_number=3)

        # Pay seat 1
        await _pay(ledger, oid, _pid(), 26.75, seat_numbers=[1])
        order = await _get_order(ledger, oid)
        assert order.paid_seats == [1]

        # Pay seat 2
        await _pay(ledger, oid, _pid(), 16.05, seat_numbers=[2])
        order = await _get_order(ledger, oid)
        assert order.paid_seats == [1, 2]

    @pytest.mark.asyncio
    async def test_paid_seats_multi_seat_single_payment(self, ledger):
        """One payment covers multiple seats at once."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00, seat_number=1)
        await _add_item(ledger, oid, "i2", "Fries", 5.00, seat_number=2)

        await _pay(ledger, oid, _pid(), 16.05, seat_numbers=[1, 2])

        order = await _get_order(ledger, oid)
        assert order.paid_seats == [1, 2]

    @pytest.mark.asyncio
    async def test_failed_payment_not_in_paid_seats(self, ledger):
        """Failed/declined payment seats are NOT included in paid_seats."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Steak", 25.00, seat_number=1)
        await _add_item(ledger, oid, "i2", "Salad", 8.00, seat_number=2)

        # Fail seat 1 payment
        await _fail_payment(ledger, oid, _pid(), 26.75, seat_numbers=[1])

        order = await _get_order(ledger, oid)
        assert order.paid_seats == []

    @pytest.mark.asyncio
    async def test_pending_payment_not_in_paid_seats(self, ledger):
        """Initiated-but-not-confirmed payment seats are NOT in paid_seats."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Steak", 25.00, seat_number=1)

        await _pay_initiated_only(ledger, oid, _pid(), 26.75, seat_numbers=[1])

        order = await _get_order(ledger, oid)
        assert order.paid_seats == []

    @pytest.mark.asyncio
    async def test_payment_without_seat_numbers_backwards_compat(self, ledger):
        """Payment without seat_numbers → paid_seats stays empty, no crash."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00, seat_number=1)

        # Pay without seat_numbers (legacy behavior)
        await _pay(ledger, oid, _pid(), 10.70)

        order = await _get_order(ledger, oid)
        assert order.paid_seats == []
        assert order.payments[0].seat_numbers == []
        assert order.amount_paid == 10.70

    @pytest.mark.asyncio
    async def test_paid_seats_deduplicates(self, ledger):
        """If same seat appears in two payments, paid_seats has it once."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "Burger", 10.00, seat_number=1)

        # Two payments both claim seat 1 (edge case: partial then remainder)
        await _pay(ledger, oid, _pid(), 5.00, seat_numbers=[1])
        await _pay(ledger, oid, _pid(), 5.70, seat_numbers=[1])

        order = await _get_order(ledger, oid)
        assert order.paid_seats == [1]

    @pytest.mark.asyncio
    async def test_paid_seats_sorted(self, ledger):
        """paid_seats returns seats in ascending order regardless of payment order."""
        oid = _oid()
        await _create_order(ledger, oid)
        await _add_item(ledger, oid, "i1", "A", 10.00, seat_number=3)
        await _add_item(ledger, oid, "i2", "B", 10.00, seat_number=1)
        await _add_item(ledger, oid, "i3", "C", 10.00, seat_number=2)

        # Pay in reverse order: seat 3 first, then seat 1
        await _pay(ledger, oid, _pid(), 10.70, seat_numbers=[3])
        await _pay(ledger, oid, _pid(), 10.70, seat_numbers=[1])

        order = await _get_order(ledger, oid)
        assert order.paid_seats == [1, 3]


# ═══════════════════════════════════════════════════════════════════════════
# 2. API ROUTE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

TEST_DB = Path("./data/test_seat_pay_api.db")


@pytest_asyncio.fixture
async def api_ledger():
    if TEST_DB.exists():
        os.remove(TEST_DB)
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def client(api_ledger):
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api import dependencies as deps

    async def _override():
        return api_ledger
    app.dependency_overrides[deps.get_ledger] = _override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


class TestSeatPaymentAPI:
    """Verify seat_numbers flows through cash/card API routes and OrderResponse."""

    @pytest.mark.asyncio
    async def test_cash_payment_with_seat_numbers(self, client, api_ledger):
        """POST /payments/cash with seat_numbers stores them in events."""
        resp = await client.post("/api/v1/orders", json={
            "table": "T-1", "server_id": "srv-01", "server_name": "Bob",
        })
        oid = resp.json()["order_id"]

        await client.post(f"/api/v1/orders/{oid}/items", json={
            "menu_item_id": "b1", "name": "Burger", "price": 10.00,
            "seat_number": 1,
        })
        await client.post(f"/api/v1/orders/{oid}/items", json={
            "menu_item_id": "f1", "name": "Fries", "price": 5.00,
            "seat_number": 2,
        })

        # Pay for seat 1 only
        resp = await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 10.70,
            "seat_numbers": [1],
        })
        assert resp.status_code == 200

        # Verify events have seat_numbers
        events = await api_ledger.get_events_by_correlation(oid)
        init_evt = next(
            e for e in events if e.event_type == EventType.PAYMENT_INITIATED
        )
        assert init_evt.payload.get("seat_numbers") == [1]

        conf_evt = next(
            e for e in events if e.event_type == EventType.PAYMENT_CONFIRMED
        )
        assert conf_evt.payload.get("seat_numbers") == [1]

    @pytest.mark.asyncio
    async def test_order_response_includes_paid_seats(self, client, api_ledger):
        """GET /orders/{id} returns paid_seats after seat payment."""
        resp = await client.post("/api/v1/orders", json={
            "table": "T-2", "server_id": "srv-01", "server_name": "Carol",
        })
        oid = resp.json()["order_id"]

        await client.post(f"/api/v1/orders/{oid}/items", json={
            "menu_item_id": "s1", "name": "Steak", "price": 30.00,
            "seat_number": 1,
        })
        await client.post(f"/api/v1/orders/{oid}/items", json={
            "menu_item_id": "p1", "name": "Pasta", "price": 15.00,
            "seat_number": 2,
        })

        # Pay seat 1
        await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 32.10,
            "seat_numbers": [1],
        })

        # Fetch order and check paid_seats
        resp = await client.get(f"/api/v1/orders/{oid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["paid_seats"] == [1]
        # Seat 2 should NOT be in paid_seats
        assert 2 not in data["paid_seats"]

    @pytest.mark.asyncio
    async def test_order_response_paid_seats_empty_without_seat_numbers(self, client, api_ledger):
        """Legacy payment without seat_numbers → paid_seats is empty list."""
        resp = await client.post("/api/v1/orders", json={"table": "T-3"})
        oid = resp.json()["order_id"]

        await client.post(f"/api/v1/orders/{oid}/items", json={
            "menu_item_id": "b1", "name": "Burger", "price": 10.00,
        })

        # Pay without seat_numbers
        await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 10.70,
        })

        resp = await client.get(f"/api/v1/orders/{oid}")
        data = resp.json()
        assert data["paid_seats"] == []

    @pytest.mark.asyncio
    async def test_payment_response_includes_seat_numbers(self, client, api_ledger):
        """OrderResponse.payments[].seat_numbers is populated."""
        resp = await client.post("/api/v1/orders", json={"table": "T-4"})
        oid = resp.json()["order_id"]

        await client.post(f"/api/v1/orders/{oid}/items", json={
            "menu_item_id": "b1", "name": "Burger", "price": 10.00,
            "seat_number": 1,
        })

        await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 10.70,
            "seat_numbers": [1],
        })

        resp = await client.get(f"/api/v1/orders/{oid}")
        data = resp.json()
        confirmed = [p for p in data["payments"] if p["status"] == "confirmed"]
        assert len(confirmed) == 1
        assert confirmed[0]["seat_numbers"] == [1]

    @pytest.mark.asyncio
    async def test_sequential_seat_payments_accumulate(self, client, api_ledger):
        """Pay seats one at a time, verify paid_seats grows."""
        resp = await client.post("/api/v1/orders", json={"table": "T-5"})
        oid = resp.json()["order_id"]

        for seat_num, name, price in [(1, "Steak", 30.00), (2, "Pasta", 15.00), (3, "Salad", 8.00)]:
            await client.post(f"/api/v1/orders/{oid}/items", json={
                "menu_item_id": f"item-{seat_num}", "name": name,
                "price": price, "seat_number": seat_num,
            })

        # Pay seat 1
        await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 32.10, "seat_numbers": [1],
        })
        resp = await client.get(f"/api/v1/orders/{oid}")
        assert resp.json()["paid_seats"] == [1]

        # Pay seat 3 (skip 2)
        await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 8.56, "seat_numbers": [3],
        })
        resp = await client.get(f"/api/v1/orders/{oid}")
        assert resp.json()["paid_seats"] == [1, 3]

    @pytest.mark.asyncio
    async def test_seat_payments_when_cash_discount_disabled(self, client, api_ledger, monkeypatch):
        """Regression: with cash_discount_rate=0, paying one seat must not
        apply a discount that zeros the balance and auto-closes the check."""
        from app.config import settings
        monkeypatch.setattr(settings, "cash_discount_rate", 0.0)

        resp = await client.post("/api/v1/orders", json={"table": "T-NoDisc"})
        oid = resp.json()["order_id"]

        for seat, name, price in [(1, "Steak", 30.00), (2, "Pasta", 15.00)]:
            await client.post(f"/api/v1/orders/{oid}/items", json={
                "menu_item_id": f"item-{seat}", "name": name,
                "price": price, "seat_number": seat,
            })

        # Pay seat 1 only — order must stay open so seat 2 can pay next.
        r1 = await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 30.00, "seat_numbers": [1],
        })
        assert r1.status_code == 200

        resp = await client.get(f"/api/v1/orders/{oid}")
        data = resp.json()
        assert data["status"] == "open", f"Order should stay open, got {data['status']}"
        assert data["paid_seats"] == [1]

        # Seat 2 payment must not be rejected by a premature close.
        r2 = await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 15.00, "seat_numbers": [2],
        })
        assert r2.status_code == 200, f"Seat 2 payment failed: {r2.text}"

        resp = await client.get(f"/api/v1/orders/{oid}")
        assert resp.json()["paid_seats"] == [1, 2]

    @pytest.mark.asyncio
    async def test_void_payment_reopens_closed_order(self, client, api_ledger, monkeypatch):
        """Voiding the last payment on a fully-paid (closed) check must
        reopen the order so the seat can be re-paid."""
        from app.config import settings
        monkeypatch.setattr(settings, "cash_discount_rate", 0.0)

        resp = await client.post("/api/v1/orders", json={"table": "T-Reopen"})
        oid = resp.json()["order_id"]

        await client.post(f"/api/v1/orders/{oid}/items", json={
            "menu_item_id": "i1", "name": "Burger", "price": 10.00,
            "seat_number": 1,
        })

        pay = await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 10.70, "seat_numbers": [1],
        })
        assert pay.status_code == 200
        pid = pay.json()["payment_id"]

        # Order auto-closed (fully paid) — voiding must still succeed and reopen it
        resp = await client.get(f"/api/v1/orders/{oid}")
        assert resp.json()["status"] == "closed"

        void = await client.post(
            f"/api/v1/orders/{oid}/payments/{pid}/void",
            json={"reason": "test reopen", "approved_by": "mgr-1"},
        )
        assert void.status_code == 200, f"Void failed: {void.text}"

        data = void.json()
        assert data["status"] == "open"
        assert data["paid_seats"] == []

        # Seat 1 can now be re-paid
        repay = await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 10.70, "seat_numbers": [1],
        })
        assert repay.status_code == 200

    @pytest.mark.asyncio
    async def test_void_payment_accepts_json_body(self, client, api_ledger, monkeypatch):
        """The void endpoint must accept reason/approved_by via JSON body."""
        from app.config import settings
        monkeypatch.setattr(settings, "cash_discount_rate", 0.0)

        resp = await client.post("/api/v1/orders", json={"table": "T-Body"})
        oid = resp.json()["order_id"]
        for seat, price in [(1, 10.0), (2, 5.0)]:
            await client.post(f"/api/v1/orders/{oid}/items", json={
                "menu_item_id": f"i{seat}", "name": f"item{seat}",
                "price": price, "seat_number": seat,
            })

        pay = await client.post("/api/v1/payments/cash", json={
            "order_id": oid, "amount": 10.0, "seat_numbers": [1],
        })
        pid = pay.json()["payment_id"]

        void = await client.post(
            f"/api/v1/orders/{oid}/payments/{pid}/void",
            json={"reason": "customer changed mind", "approved_by": "mgr-42"},
        )
        assert void.status_code == 200

        events = await api_ledger.get_events_by_correlation(oid)
        cancelled = [e for e in events if e.event_type == EventType.PAYMENT_CANCELLED]
        assert len(cancelled) == 1
        assert cancelled[0].payload["error"] == "customer changed mind"
        assert cancelled[0].payload["approved_by"] == "mgr-42"
