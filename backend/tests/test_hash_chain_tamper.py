"""
Hash Chain Tamper Detection Tests
=================================
Verifies that EventLedger.verify_chain() detects:
  - Tampered hash (checksum) columns
  - Tampered data (payload) columns
  - Deleted middle events
  - Empty ledger passes cleanly
"""

import os
import pytest
import pytest_asyncio
from pathlib import Path

from app.core.event_ledger import EventLedger
from app.core.events import Event, EventType, create_event


# ─── Isolated test database ────────────────────────────────
TAMPER_TEST_DB = Path("./data/test_hash_chain_tamper.db")


@pytest_asyncio.fixture
async def tamper_ledger():
    """Fresh EventLedger for tamper-detection tests."""
    if TAMPER_TEST_DB.exists():
        os.remove(TAMPER_TEST_DB)

    async with EventLedger(str(TAMPER_TEST_DB)) as _ledger:
        yield _ledger

    if TAMPER_TEST_DB.exists():
        os.remove(TAMPER_TEST_DB)


async def _insert_events(ledger: EventLedger, count: int = 5) -> list[Event]:
    """Insert `count` events and return them (with sequence numbers)."""
    appended = []
    for i in range(count):
        evt = create_event(
            event_type=EventType.ORDER_CREATED,
            terminal_id="terminal-test-01",
            payload={"order_number": i + 1, "items": [f"item-{i + 1}"]},
            user_id="test-user",
            user_role="cashier",
        )
        appended.append(await ledger.append(evt))
    return appended


# ─── Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intact_chain_passes(tamper_ledger):
    """Insert 5+ events, verify_chain returns (True, None)."""
    await _insert_events(tamper_ledger, count=6)

    is_valid, invalid_seq = await tamper_ledger.verify_chain()
    assert is_valid is True
    assert invalid_seq is None


@pytest.mark.asyncio
async def test_tampered_hash_detected(tamper_ledger):
    """Overwrite one event's checksum via raw SQL; verify_chain must catch it."""
    events = await _insert_events(tamper_ledger, count=5)

    # Tamper with the 3rd event's checksum
    target = events[2]
    await tamper_ledger._db.execute(
        "UPDATE events SET checksum = ? WHERE sequence_number = ?",
        ("deadbeef" * 8, target.sequence_number),
    )
    await tamper_ledger._db.commit()

    is_valid, invalid_seq = await tamper_ledger.verify_chain()
    assert is_valid is False
    assert invalid_seq == target.sequence_number


@pytest.mark.asyncio
async def test_tampered_data_detected(tamper_ledger):
    """Overwrite one event's payload via raw SQL; verify_chain must catch it."""
    events = await _insert_events(tamper_ledger, count=5)

    # Tamper with the 4th event's payload (data, not hash)
    target = events[3]
    await tamper_ledger._db.execute(
        "UPDATE events SET payload = ? WHERE sequence_number = ?",
        ('{"order_number": 999, "items": ["TAMPERED"]}', target.sequence_number),
    )
    await tamper_ledger._db.commit()

    is_valid, invalid_seq = await tamper_ledger.verify_chain()
    assert is_valid is False
    assert invalid_seq == target.sequence_number


@pytest.mark.asyncio
async def test_deleted_middle_event_detected(tamper_ledger):
    """Delete a middle event via raw SQL; verify_chain must catch it."""
    events = await _insert_events(tamper_ledger, count=5)

    # Delete the 3rd event (index 2)
    deleted = events[2]
    await tamper_ledger._db.execute(
        "DELETE FROM events WHERE sequence_number = ?",
        (deleted.sequence_number,),
    )
    await tamper_ledger._db.commit()

    is_valid, invalid_seq = await tamper_ledger.verify_chain()
    assert is_valid is False
    # The event after the gap should be the one flagged
    assert invalid_seq == events[3].sequence_number


@pytest.mark.asyncio
async def test_empty_ledger_passes(tamper_ledger):
    """An empty ledger should pass verification without error."""
    is_valid, invalid_seq = await tamper_ledger.verify_chain()
    assert is_valid is True
    assert invalid_seq is None
