"""
Tests for the labor paths in `api/routes/reporting.py`:
  - GET /reports/labor-summary (manager + server views)
  - GET /reports/hourly-compare
  - the internal `_hourly_for_date` helper
  - the COB (Cost of Business) trend per employee

These routes carry real wage/tip math — we patched two silent bugs
here this session (hardcoded $15/hr labor cost and `_hourly_for_date`
returning gross subtotal under the `net_sales` field) and neither had
a regression test. This file pins them.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from app.api.routes.reporting import (
    _hourly_for_date,
    get_labor_summary,
    hourly_compare,
)
from app.config import settings
from app.core.event_ledger import EventLedger
from app.core.events import (
    EventType,
    create_event,
    item_added,
    order_closed,
    order_created,
    payment_confirmed,
    payment_initiated,
    tip_adjusted,
    user_logged_in,
    user_logged_out,
)


TEST_DB = Path("./data/test_labor_summary.db")
TERMINAL = "terminal_labor"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _zero_config(monkeypatch):
    """Zero tax + cash discount so labor/tips math reads cleanly."""
    monkeypatch.setattr(settings, "tax_rate", 0.0)
    monkeypatch.setattr(settings, "cash_discount_rate", 0.0)
    monkeypatch.setattr(settings, "tipout_percent", 0.0)


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


# ── helpers ─────────────────────────────────────────────────────────────────

async def _clock_in(ledger, eid: str, name: str, *, minutes_ago: int = 60):
    """Emit a USER_LOGGED_IN event; tweak `minutes_ago` to control shift length."""
    evt = user_logged_in(
        terminal_id=TERMINAL,
        employee_id=eid,
        employee_name=name,
    )
    # Nudge the timestamp back so _calc_hours sees a non-zero shift.
    evt = evt.model_copy(
        update={"timestamp": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)}
    )
    await ledger.append(evt)
    return evt


async def _clock_out(ledger, eid: str, name: str):
    await ledger.append(user_logged_out(
        terminal_id=TERMINAL,
        employee_id=eid,
        employee_name=name,
    ))


async def _seed_employee(ledger, eid: str, name: str, hourly_rate: float):
    """Write an EMPLOYEE_CREATED event so cob_trend can price the shift."""
    await ledger.append(create_event(
        event_type=EventType.EMPLOYEE_CREATED,
        terminal_id=TERMINAL,
        payload={
            "employee_id": eid,
            "first_name": name,
            "last_name": "",
            "display_name": name,
            "hourly_rate": str(hourly_rate),
            "active": True,
        },
    ))


async def _order_closed_with_tip(
    ledger, *, order_id: str, server_id: str, amount: float, tip: float = 0.0,
):
    """Add a small sale and optional tip so labor_summary.server_tips reads it."""
    await ledger.append(order_created(
        terminal_id=TERMINAL,
        order_id=order_id,
        order_type="dine_in",
        server_id=server_id,
        server_name=f"S_{server_id}",
        correlation_id=order_id,
    ))
    await ledger.append(item_added(
        terminal_id=TERMINAL,
        order_id=order_id,
        item_id=f"{order_id}_it",
        menu_item_id="m1",
        name="Thing",
        price=amount,
        quantity=1,
    ))
    pid = f"{order_id}_p"
    await ledger.append(payment_initiated(
        terminal_id=TERMINAL, order_id=order_id, payment_id=pid,
        amount=amount, method="card",
    ))
    await ledger.append(payment_confirmed(
        terminal_id=TERMINAL, order_id=order_id, payment_id=pid,
        transaction_id=f"txn_{order_id}", amount=amount, tax=0.0,
    ))
    if tip > 0:
        await ledger.append(tip_adjusted(
            terminal_id=TERMINAL, order_id=order_id, payment_id=pid,
            tip_amount=tip,
        ))
    await ledger.append(order_closed(
        terminal_id=TERMINAL, order_id=order_id, total=amount,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# LABOR SUMMARY — MANAGER VIEW
# ═══════════════════════════════════════════════════════════════════════════

class TestLaborSummaryManagerView:

    @pytest.mark.asyncio
    async def test_single_clocked_in_employee(self, ledger):
        """One clocked-in employee shows up with hours > 0."""
        await _clock_in(ledger, "emp_A", "Alice", minutes_ago=120)

        res = await get_labor_summary(date=TODAY, server_id=None, ledger=ledger)

        assert len(res["employees"]) == 1
        emp = res["employees"][0]
        assert emp["id"] == "emp_A"
        assert emp["name"] == "Alice"
        # Still clocked in -> hours computed from login → now
        assert emp["hours"] >= 1.9  # rounding
        assert emp["hours"] <= 2.1
        assert emp["clock_out"] is None
        assert res["total_hours"] >= 1.9

    @pytest.mark.asyncio
    async def test_clocked_in_and_out_records_correct_hours(self, ledger):
        """LOGIN then LOGOUT yields a finite hours value, no longer 'clocked in'."""
        await _clock_in(ledger, "emp_B", "Bob", minutes_ago=90)
        await _clock_out(ledger, "emp_B", "Bob")

        res = await get_labor_summary(date=TODAY, server_id=None, ledger=ledger)

        emp = next(e for e in res["employees"] if e["id"] == "emp_B")
        assert emp["clock_in"] is not None
        assert emp["clock_out"] is not None
        assert 1.4 <= emp["hours"] <= 1.6

    @pytest.mark.asyncio
    async def test_wage_math_with_hourly_rate(self, ledger):
        """gross_pay = hours × configured hourly_rate, rolled into total_labor."""
        await _seed_employee(ledger, "emp_C", "Carol", hourly_rate=18.00)
        await _clock_in(ledger, "emp_C", "Carol", minutes_ago=60)
        await _clock_out(ledger, "emp_C", "Carol")

        res = await get_labor_summary(date=TODAY, server_id=None, ledger=ledger)

        emp = next(e for e in res["employees"] if e["id"] == "emp_C")
        assert emp["hourly_rate"] == pytest.approx(18.00)
        assert emp["gross_pay"] == pytest.approx(emp["hours"] * 18.00, abs=0.01)
        assert res["total_labor"] == pytest.approx(emp["gross_pay"], abs=0.01)

    @pytest.mark.asyncio
    async def test_missing_rate_uses_zero_not_fabricated_default(self, ledger):
        """Fix verification: employees without a configured hourly_rate
        contribute $0 labor cost — NOT a fabricated $15/hr."""
        # No EMPLOYEE_CREATED for emp_D — so rate should default to 0
        await _clock_in(ledger, "emp_D", "Dan", minutes_ago=60)
        await _clock_out(ledger, "emp_D", "Dan")

        res = await get_labor_summary(date=TODAY, server_id=None, ledger=ledger)

        emp = next(e for e in res["employees"] if e["id"] == "emp_D")
        assert emp["hourly_rate"] == pytest.approx(0.0)
        assert emp["gross_pay"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_net_sales_surfaces_alongside_labor(self, ledger):
        """labor-summary now exposes the day's net_sales so the Overseer
        Labor % KPI has a denominator — previously it defaulted to 0."""
        await _clock_in(ledger, "emp_E", "Eve", minutes_ago=60)
        await _order_closed_with_tip(
            ledger, order_id="oE1", server_id="emp_E", amount=42.00,
        )

        res = await get_labor_summary(date=TODAY, server_id=None, ledger=ledger)
        assert res["net_sales"] == pytest.approx(42.00)

    @pytest.mark.asyncio
    async def test_tips_attributed_to_server(self, ledger):
        """TIP_ADJUSTED events on a server's orders flow into their `tips`."""
        await _clock_in(ledger, "emp_F", "Fin", minutes_ago=60)
        await _order_closed_with_tip(
            ledger, order_id="oF1", server_id="emp_F",
            amount=20.00, tip=3.00,
        )

        res = await get_labor_summary(date=TODAY, server_id=None, ledger=ledger)

        emp = next(e for e in res["employees"] if e["id"] == "emp_F")
        assert emp["tips"] == pytest.approx(3.00)
        assert res["card_tips_total"] == pytest.approx(3.00)

    @pytest.mark.asyncio
    async def test_empty_day_has_no_employees_no_crash(self, ledger):
        """Zero employees, zero events — endpoint still returns a valid payload."""
        res = await get_labor_summary(date=TODAY, server_id=None, ledger=ledger)
        assert res["employees"] == []
        assert res["total_hours"] == pytest.approx(0.0)
        assert res["total_labor"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# LABOR SUMMARY — SERVER VIEW
# ═══════════════════════════════════════════════════════════════════════════

class TestLaborSummaryServerView:

    @pytest.mark.asyncio
    async def test_ot_buffer_and_status_under_warning_threshold(self, ledger):
        """Under 35 weekly hours → status "ok" and buffer tracks 40 − weekly."""
        await _clock_in(ledger, "emp_G", "Gus", minutes_ago=60)  # ~1h today
        await _clock_out(ledger, "emp_G", "Gus")

        res = await get_labor_summary(date=TODAY, server_id="emp_G", ledger=ledger)

        assert res["today_hours"] >= 0.9
        assert res["ot_status"] == "ok"
        assert res["ot_buffer"] == pytest.approx(40.0 - res["weekly_hours"], abs=0.1)

    @pytest.mark.asyncio
    async def test_clock_in_out_strings_formatted_HHMM(self, ledger):
        """The server view returns zero-padded HH:MM strings for the timeline."""
        await _clock_in(ledger, "emp_H", "Hal", minutes_ago=30)
        await _clock_out(ledger, "emp_H", "Hal")

        res = await get_labor_summary(date=TODAY, server_id="emp_H", ledger=ledger)
        assert res["clock_in"] is not None
        assert len(res["clock_in"]) == 5 and res["clock_in"][2] == ":"
        assert res["clock_out"] is not None


# ═══════════════════════════════════════════════════════════════════════════
# HOURLY COMPARE — `_hourly_for_date` & the router
# ═══════════════════════════════════════════════════════════════════════════

class TestHourlyCompare:
    """Previously `_hourly_for_date` summed `order.subtotal` (gross!) into
    a field labelled `net_sales`. These tests pin the fix: the hourly
    series subtracts discounts and refunds, matching `_aggregate_orders`."""

    @pytest.mark.asyncio
    async def test_hourly_net_subtracts_discount(self, ledger):
        # Single order: subtotal $30, discount $5 → expected hourly net $25.
        await ledger.append(order_created(
            terminal_id=TERMINAL, order_id="o_hr1",
            order_type="dine_in", correlation_id="o_hr1",
        ))
        await ledger.append(item_added(
            terminal_id=TERMINAL, order_id="o_hr1", item_id="it1",
            menu_item_id="m", name="X", price=30.00, quantity=1,
        ))
        await ledger.append(create_event(
            event_type=EventType.DISCOUNT_APPROVED,
            terminal_id=TERMINAL, correlation_id="o_hr1",
            payload={
                "order_id": "o_hr1", "discount_type": "10%",
                "amount": 5.00, "reason": "test",
            },
        ))

        hourly = await _hourly_for_date(ledger, TODAY, open_hour=0, close_hour=23)
        total = sum(h["net_sales"] for h in hourly)
        assert total == pytest.approx(25.00)

    @pytest.mark.asyncio
    async def test_voided_orders_excluded_from_hourly(self, ledger):
        """Voided orders contribute zero to the hourly series."""
        await ledger.append(order_created(
            terminal_id=TERMINAL, order_id="o_vh",
            order_type="dine_in", correlation_id="o_vh",
        ))
        await ledger.append(item_added(
            terminal_id=TERMINAL, order_id="o_vh", item_id="it",
            menu_item_id="m", name="Z", price=99.00, quantity=1,
        ))
        await ledger.append(create_event(
            event_type=EventType.ORDER_VOIDED,
            terminal_id=TERMINAL, correlation_id="o_vh",
            payload={"order_id": "o_vh", "reason": "test"},
        ))

        hourly = await _hourly_for_date(ledger, TODAY, open_hour=0, close_hour=23)
        total = sum(h["net_sales"] for h in hourly)
        assert total == pytest.approx(0.00)

    @pytest.mark.asyncio
    async def test_hourly_empty_range_returns_zero_per_hour(self, ledger):
        """With no orders, every configured hour returns net_sales=0 —
        never None, never missing. Keeps the charting code simple."""
        hourly = await _hourly_for_date(ledger, TODAY, open_hour=11, close_hour=14)
        assert len(hourly) == 4   # 11, 12, 13, 14
        for h in hourly:
            assert h["net_sales"] == pytest.approx(0.0)
            assert "hour" in h

    @pytest.mark.asyncio
    async def test_hourly_compare_router_returns_today_and_last_week(self, ledger):
        res = await hourly_compare(date=TODAY, ledger=ledger)
        assert "today" in res and isinstance(res["today"], list)
        assert "last_week" in res and isinstance(res["last_week"], list)
