"""
Tests for the demo data seeder.

Covers:
    - seeding on an empty database
    - idempotency (second call is a no-op)
    - restaurant config seeding
"""

import os
import pytest

from app.core.event_ledger import EventLedger
from app.core.events import EventType
from app.services.demo_seeder import seed_demo_data_if_empty


# Path to the demo seed file used by the seeder
SEED_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'data', 'demo_seed.json')
)


@pytest.fixture
def has_seed_file():
    return os.path.exists(SEED_PATH)


# ─── Tests ──────────────────────────────────────────────────────────────────

async def test_seeds_on_empty_db(tmp_path, has_seed_file):
    """Seeder creates EMPLOYEE_CREATED events on an empty ledger."""
    if not has_seed_file:
        pytest.skip("demo_seed.json not found")

    db_path = str(tmp_path / "test_seeder.db")
    async with EventLedger(db_path) as ledger:
        await seed_demo_data_if_empty(ledger)

        events = await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED)
        assert len(events) > 0


async def test_idempotent(tmp_path, has_seed_file):
    """Calling seeder twice produces the same number of EMPLOYEE_CREATED events."""
    if not has_seed_file:
        pytest.skip("demo_seed.json not found")

    db_path = str(tmp_path / "test_seeder_idem.db")
    async with EventLedger(db_path) as ledger:
        await seed_demo_data_if_empty(ledger)
        count_after_first = len(
            await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED)
        )

        await seed_demo_data_if_empty(ledger)
        count_after_second = len(
            await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED)
        )

        assert count_after_first == count_after_second
        assert count_after_first > 0


async def test_seeds_restaurant_config(tmp_path, has_seed_file):
    """Seeder creates a STORE_INFO_UPDATED event."""
    if not has_seed_file:
        pytest.skip("demo_seed.json not found")

    db_path = str(tmp_path / "test_seeder_config.db")
    async with EventLedger(db_path) as ledger:
        await seed_demo_data_if_empty(ledger)

        events = await ledger.get_events_by_type(EventType.STORE_INFO_UPDATED)
        assert len(events) == 1
