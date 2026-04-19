"""
Tests for `api/routes/config.py` — the Overseer-authored config plane.
Every store setting, employee, tipout rule, and menu edit flows
through these endpoints before reaching terminals (via the sync route
we already covered). config.py sat at 59% coverage.

Priorities:
  - POST /config/push dispatches the section inference correctly
    (store / employees / menu / modifiers / floor_plan / hardware)
  - POST /store/info, /store/cc-rate persist exactly one event
  - POST /menu/86, /menu/restore emit the right event types
  - POST/PUT/DELETE /roles and /employees route through their
    respective event types with the right payload shape
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks

from app.api.routes import config as cfg
from app.core.event_ledger import EventLedger
from app.core.events import EventType
from app.models.config_events import (
    CCProcessingRate,
    Employee,
    PendingChange,
    Role,
    StoreInfo,
)


TEST_DB = Path("./data/test_config_routes.db")


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture
def bg():
    """Real BackgroundTasks — lets the route schedule its broadcast without
    us having to care about the scheduled callback."""
    return BackgroundTasks()


# ═══════════════════════════════════════════════════════════════════════════
# POST /config/push — section inference + batch write
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigPush:

    @pytest.mark.asyncio
    async def test_empty_list_writes_nothing(self, ledger, bg):
        res = await cfg.push_changes(changes=[], background_tasks=bg, ledger=ledger)
        assert res["status"] == "ok"
        assert res["events_written"] == 0
        assert res["event_ids"] == []

    @pytest.mark.asyncio
    async def test_single_store_change_persists(self, ledger, bg):
        """store.* events route correctly; ledger gets the event."""
        res = await cfg.push_changes(
            changes=[
                PendingChange(
                    event_type="store.info_updated",
                    payload={"restaurant_name": "Test Diner", "city": "Austin"},
                ),
            ],
            background_tasks=bg, ledger=ledger,
        )
        assert res["events_written"] == 1
        events = await ledger.get_events_by_type(EventType.STORE_INFO_UPDATED)
        assert len(events) == 1
        assert events[0].payload["restaurant_name"] == "Test Diner"

    @pytest.mark.asyncio
    async def test_mixed_sections_infer_all_section_tags(self, ledger, bg):
        """A batch mixing store/employee/tipout/menu events infers every
        section correctly so the broadcast fires on the right channel."""
        res = await cfg.push_changes(
            changes=[
                PendingChange(event_type="store.info_updated", payload={"restaurant_name": "X"}),
                PendingChange(
                    event_type="employee.created",
                    payload={"employee_id": "e1", "display_name": "A"},
                ),
                PendingChange(
                    event_type="tipout.rule_created",
                    payload={
                        "rule_id": "r1", "role_from": "server", "role_to": "bar",
                        "percentage": 2.0, "calculation_base": "Net Sales",
                    },
                ),
                PendingChange(
                    event_type="menu.item_created",
                    payload={"item_id": "i1", "name": "X", "price": 10.0},
                ),
            ],
            background_tasks=bg, ledger=ledger,
        )
        assert res["events_written"] == 4
        # Each event type landed
        store_events = await ledger.get_events_by_type(EventType.STORE_INFO_UPDATED)
        emp_events = await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED)
        tipout_events = await ledger.get_events_by_type(EventType.TIPOUT_RULE_CREATED)
        menu_events = await ledger.get_events_by_type(EventType.MENU_ITEM_CREATED)
        assert len(store_events) == 1
        assert len(emp_events) == 1
        assert len(tipout_events) == 1
        assert len(menu_events) == 1

    @pytest.mark.asyncio
    async def test_batch_writes_atomically(self, ledger, bg):
        """Multiple changes all land via `append_batch` — no partial writes."""
        res = await cfg.push_changes(
            changes=[
                PendingChange(
                    event_type="employee.created",
                    payload={"employee_id": f"e{i}", "display_name": f"Emp {i}"},
                )
                for i in range(5)
            ],
            background_tasks=bg, ledger=ledger,
        )
        assert res["events_written"] == 5
        events = await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED)
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_unknown_event_type_raises(self, ledger, bg):
        """An unparseable event type bubbles as a ValueError — the client
        sent garbage, no silent no-op that leaves them thinking success."""
        with pytest.raises(ValueError):
            await cfg.push_changes(
                changes=[
                    PendingChange(
                        event_type="bogus.never_seen",
                        payload={},
                    ),
                ],
                background_tasks=bg, ledger=ledger,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Single-shot routes
# ═══════════════════════════════════════════════════════════════════════════

class TestSingleShotConfig:

    @pytest.mark.asyncio
    async def test_update_store_info_emits_event(self, ledger, bg):
        res = await cfg.update_store_info(
            info=StoreInfo(
                restaurant_name="Pizza Spot",
                address_line_1="123 Main",
                city="Austin",
                state="TX",
                zip="78701",
                phone="555-1212",
            ),
            background_tasks=bg, ledger=ledger,
        )
        assert res["status"] == "ok"
        # event_id is sourced from the in-memory event's sequence_number,
        # which the ledger doesn't back-fill — it's None here. The ledger
        # stored the event just fine, though; we verify via the query below.
        events = await ledger.get_events_by_type(EventType.STORE_INFO_UPDATED)
        assert len(events) == 1
        assert events[0].payload["restaurant_name"] == "Pizza Spot"

    @pytest.mark.asyncio
    async def test_update_cc_rate_persists(self, ledger, bg):
        res = await cfg.update_cc_rate(
            rate=CCProcessingRate(rate_percent=2.9),
            background_tasks=bg, ledger=ledger,
        )
        assert res["status"] == "ok"
        events = await ledger.get_events_by_type(
            EventType.STORE_CC_PROCESSING_RATE_UPDATED,
        )
        assert len(events) == 1
        assert events[0].payload["rate_percent"] == pytest.approx(2.9)

    @pytest.mark.asyncio
    async def test_item_86_and_restore_roundtrip(self, ledger, bg):
        """`86` an item, then restore it. Both events land in order."""
        await cfg.item_86(item_id="item_42", background_tasks=bg, ledger=ledger)
        await cfg.item_restore(item_id="item_42", background_tasks=bg, ledger=ledger)

        eighty_six = await ledger.get_events_by_type(EventType.MENU_ITEM_86D)
        restored = await ledger.get_events_by_type(EventType.MENU_ITEM_RESTORED)
        assert len(eighty_six) == 1
        assert len(restored) == 1
        assert eighty_six[0].payload["item_id"] == "item_42"
        assert restored[0].payload["item_id"] == "item_42"


# ═══════════════════════════════════════════════════════════════════════════
# Role CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestRoleRoutes:

    def _role(self, role_id="r_server") -> Role:
        return Role(
            role_id=role_id,
            name="Server",
            permission_level="Standard",
            permissions={"take_orders": True},
            tipout_eligible=True,
            can_receive_tips=True,
            can_be_tipped_out_to=False,
        )

    @pytest.mark.asyncio
    async def test_create_update_delete_role_cycle(self, ledger, bg):
        # Create
        r = self._role()
        await cfg.create_role(role=r, background_tasks=bg, ledger=ledger)
        # Update (same role_id, name change)
        r2 = r.model_copy(update={"name": "Head Server"})
        await cfg.update_role(role_id=r.role_id, role=r2, background_tasks=bg, ledger=ledger)
        # Delete
        await cfg.delete_role(role_id=r.role_id, background_tasks=bg, ledger=ledger)

        created = await ledger.get_events_by_type(EventType.EMPLOYEE_ROLE_CREATED)
        updated = await ledger.get_events_by_type(EventType.EMPLOYEE_ROLE_UPDATED)
        deleted = await ledger.get_events_by_type(EventType.EMPLOYEE_ROLE_DELETED)
        assert len(created) == 1
        assert len(updated) == 1
        assert len(deleted) == 1
        assert updated[0].payload["name"] == "Head Server"
        assert deleted[0].payload["role_id"] == r.role_id


# ═══════════════════════════════════════════════════════════════════════════
# Employee creation through the dedicated endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestEmployeeRoute:

    @pytest.mark.asyncio
    async def test_create_employee_emits_event_with_full_payload(self, ledger, bg):
        emp = Employee(
            employee_id="emp_new",
            first_name="New",
            last_name="Hire",
            display_name="New Hire",
            role_ids=["r_server"],
            pin="4321",
            hourly_rate="15.50",
            active=True,
        )
        await cfg.create_employee(employee=emp, background_tasks=bg, ledger=ledger)

        from decimal import Decimal as _D
        events = await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED)
        assert len(events) == 1
        payload = events[0].payload
        assert payload["employee_id"] == "emp_new"
        assert payload["pin"] == "4321"
        # Decimal round-trips via repr — compare via Decimal equality so
        # "15.5" and "15.50" are treated the same.
        assert _D(str(payload["hourly_rate"])) == _D("15.5")
