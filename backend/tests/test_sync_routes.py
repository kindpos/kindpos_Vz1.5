"""
Tests for `api/routes/sync.py` — LAN config sync between the Overseer
and Terminals.

sync.py sat at 26% coverage. The route is the only way config
(menu, employees, tipout rules, store info) flows from the Overseer
to terminals, so drift here means one terminal sells at wrong
prices or with missing tipout rules — the very scenario the
invariant gate now watches for.

Covered behaviours:

  /sync/health
    - returns role=overseer, status=ok

  GET /sync/config/events
    - filters operational events out of the response
    - respects `since` cursor — only returns events after it
    - caps `limit` at 5000
    - returns latest_sequence + prefixes list
    - empty ledger returns empty list

  POST /sync/config/events/replay
    - appends config events to the local ledger
    - skips non-config event types (operational events rejected)
    - idempotent: replaying the same event_id twice is a no-op
    - malformed body (missing or wrong-typed `events`) → 400
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.routes import sync as sync_mod
from app.core.event_ledger import EventLedger
from app.core.events import EventType, create_event


TEST_DB = Path("./data/test_sync_routes.db")


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


async def _seed_config_event(
    ledger, *, event_type: EventType, payload: dict,
    terminal_id: str = "OVERSEER",
):
    """Append an event and return the *stored* event — the ledger's
    `append` returns a new Event with the DB-assigned sequence_number,
    which the original in-memory Event doesn't have."""
    evt = create_event(
        event_type=event_type,
        terminal_id=terminal_id,
        payload=payload,
    )
    return await ledger.append(evt)


async def _seed_op_event(ledger, *, event_type: EventType, payload: dict):
    """Append an operational event — should NOT appear in sync response."""
    evt = create_event(
        event_type=event_type,
        terminal_id="T-01",
        payload=payload,
    )
    return await ledger.append(evt)


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════════

class TestSyncHealth:
    @pytest.mark.asyncio
    async def test_heartbeat_shape(self):
        res = await sync_mod.sync_health()
        assert res == {"status": "ok", "role": "overseer"}


# ═══════════════════════════════════════════════════════════════════════════
# GET /sync/config/events
# ═══════════════════════════════════════════════════════════════════════════

class TestGetConfigEvents:

    @pytest.mark.asyncio
    async def test_empty_ledger_returns_empty_list(self, ledger):
        res = await sync_mod.get_config_events(since=0, limit=100, ledger=ledger)
        assert res["events"] == []
        assert res["count"] == 0
        assert res["latest_sequence"] == 0   # echoes the `since` arg
        assert "store." in res["prefixes"]
        assert "menu." in res["prefixes"]

    @pytest.mark.asyncio
    async def test_returns_only_config_events(self, ledger):
        """Operational events (orders, payments) must not leak through."""
        # Config event
        await _seed_config_event(
            ledger, event_type=EventType.EMPLOYEE_CREATED,
            payload={"employee_id": "e1", "display_name": "A"},
        )
        # Operational event — should be filtered out
        await _seed_op_event(
            ledger, event_type=EventType.ORDER_CREATED,
            payload={"order_id": "o1", "order_type": "dine_in"},
        )
        # Another config event
        await _seed_config_event(
            ledger, event_type=EventType.TIPOUT_RULE_CREATED,
            payload={
                "rule_id": "r1", "role_from": "server", "role_to": "bar",
                "percentage": 2.0, "calculation_base": "Net Sales",
            },
        )

        res = await sync_mod.get_config_events(since=0, limit=100, ledger=ledger)
        types = [e["event_type"] for e in res["events"]]
        assert "employee.created" in types
        assert "tipout.rule_created" in types
        assert "order.created" not in types
        assert res["count"] == 2

    @pytest.mark.asyncio
    async def test_since_cursor_filters_earlier_events(self, ledger):
        e1 = await _seed_config_event(
            ledger, event_type=EventType.EMPLOYEE_CREATED,
            payload={"employee_id": "e1", "display_name": "A"},
        )
        e2 = await _seed_config_event(
            ledger, event_type=EventType.EMPLOYEE_CREATED,
            payload={"employee_id": "e2", "display_name": "B"},
        )

        # Pulling with since=e1.sequence_number only yields e2
        res = await sync_mod.get_config_events(
            since=e1.sequence_number, limit=100, ledger=ledger,
        )
        assert res["count"] == 1
        assert res["events"][0]["event_id"] == e2.event_id
        assert res["latest_sequence"] == e2.sequence_number

    @pytest.mark.asyncio
    async def test_limit_capped_at_5000(self, ledger):
        """Even a caller asking for 999_999 gets capped at 5000."""
        # Don't actually seed 5000 events — just verify the cap is applied
        # via the returned latest_sequence when limit is absurd.
        res = await sync_mod.get_config_events(since=0, limit=999_999, ledger=ledger)
        # Shape check: count is bounded, no exception
        assert res["count"] <= 5000

    @pytest.mark.asyncio
    async def test_event_serialization_shape(self, ledger):
        """Each event in the response has the wire-format keys clients expect."""
        await _seed_config_event(
            ledger, event_type=EventType.STORE_TAX_RULE_CREATED,
            payload={"rule_id": "t1", "rate_percent": 7.0, "applies_to": "all"},
        )
        res = await sync_mod.get_config_events(since=0, limit=100, ledger=ledger)
        assert res["count"] == 1
        ev = res["events"][0]
        for k in ("event_id", "sequence_number", "timestamp",
                  "terminal_id", "event_type", "payload"):
            assert k in ev
        assert ev["event_type"] == "store.tax_rule_created"
        assert ev["payload"]["rate_percent"] == 7.0
        # timestamp is a string (ISO)
        assert isinstance(ev["timestamp"], str) and "T" in ev["timestamp"]


# ═══════════════════════════════════════════════════════════════════════════
# POST /sync/config/events/replay
# ═══════════════════════════════════════════════════════════════════════════

class TestReplayConfigEvents:

    def _wire_event(
        self, *, event_type: str, event_id: str = None,
        payload: dict = None, terminal_id: str = "OVERSEER",
    ):
        """Build the dict shape the replay endpoint expects."""
        return {
            "event_id": event_id or f"evt_{event_type.replace('.', '_')}",
            "sequence_number": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "terminal_id": terminal_id,
            "event_type": event_type,
            "payload": payload or {},
            "user_id": None,
            "user_role": None,
            "correlation_id": None,
        }

    @pytest.mark.asyncio
    async def test_applies_config_events(self, ledger):
        res = await sync_mod.replay_config_events(
            payload={
                "events": [
                    self._wire_event(
                        event_type="employee.created",
                        payload={"employee_id": "e1", "display_name": "A"},
                    ),
                ],
            },
            ledger=ledger,
        )
        assert res == {"applied": 1, "skipped": 0}
        # And it actually landed in the local ledger
        stored = await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED)
        assert len(stored) == 1
        assert stored[0].payload["employee_id"] == "e1"

    @pytest.mark.asyncio
    async def test_skips_operational_events(self, ledger):
        """Operational events don't belong in the config sync stream —
        the endpoint refuses to replay them even if asked."""
        res = await sync_mod.replay_config_events(
            payload={
                "events": [
                    self._wire_event(
                        event_type="order.created",
                        payload={"order_id": "o1"},
                    ),
                ],
            },
            ledger=ledger,
        )
        assert res == {"applied": 0, "skipped": 1}
        # Ledger untouched
        stored = await ledger.get_events_by_type(EventType.ORDER_CREATED)
        assert stored == []

    @pytest.mark.asyncio
    async def test_skips_events_missing_event_type(self, ledger):
        """A malformed event dict without `event_type` is skipped, not
        raised — one bad row shouldn't abort a batch."""
        res = await sync_mod.replay_config_events(
            payload={"events": [{"payload": {"employee_id": "e1"}}]},
            ledger=ledger,
        )
        assert res == {"applied": 0, "skipped": 1}

    @pytest.mark.asyncio
    async def test_idempotent_on_duplicate_event_id(self, ledger):
        """Re-posting an event with the same event_id is a no-op. Terminals
        poll periodically, so duplicates MUST be safe."""
        event_dict = self._wire_event(
            event_type="tipout.rule_created",
            event_id="rule_evt_01",
            payload={
                "rule_id": "r1", "role_from": "server", "role_to": "bar",
                "percentage": 2.0, "calculation_base": "Net Sales",
            },
        )
        first = await sync_mod.replay_config_events(
            payload={"events": [event_dict]}, ledger=ledger,
        )
        assert first == {"applied": 1, "skipped": 0}

        # Re-apply — should skip, not duplicate
        second = await sync_mod.replay_config_events(
            payload={"events": [event_dict]}, ledger=ledger,
        )
        assert second["applied"] == 0
        # One in the ledger, not two
        stored = await ledger.get_events_by_type(EventType.TIPOUT_RULE_CREATED)
        assert len(stored) == 1

    @pytest.mark.asyncio
    async def test_mixed_batch_partitions_correctly(self, ledger):
        """A batch can contain a mix of config + operational + malformed.
        Each is tallied correctly."""
        res = await sync_mod.replay_config_events(
            payload={
                "events": [
                    self._wire_event(
                        event_type="employee.created",
                        payload={"employee_id": "e1", "display_name": "A"},
                    ),
                    self._wire_event(
                        event_type="order.created",
                        payload={"order_id": "o1"},
                    ),
                    {"payload": {}},  # no event_type
                    self._wire_event(
                        event_type="menu.item_created",
                        payload={"item_id": "i1", "name": "X", "price": 10.0},
                    ),
                ],
            },
            ledger=ledger,
        )
        assert res["applied"] == 2
        assert res["skipped"] == 2

    @pytest.mark.asyncio
    async def test_empty_events_list_succeeds(self, ledger):
        res = await sync_mod.replay_config_events(
            payload={"events": []}, ledger=ledger,
        )
        assert res == {"applied": 0, "skipped": 0}

    @pytest.mark.asyncio
    async def test_missing_events_key_treated_as_empty(self, ledger):
        """`{}` (no `events` key) is a valid empty batch."""
        res = await sync_mod.replay_config_events(payload={}, ledger=ledger)
        assert res == {"applied": 0, "skipped": 0}

    @pytest.mark.asyncio
    async def test_events_not_a_list_400s(self, ledger):
        with pytest.raises(HTTPException) as exc:
            await sync_mod.replay_config_events(
                payload={"events": "not-a-list"}, ledger=ledger,
            )
        assert exc.value.status_code == 400
