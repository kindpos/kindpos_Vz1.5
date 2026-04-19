"""Hash chain integrity probe — walks the event ledger and verifies every SHA-256 hash."""

import hashlib
import json
import os
import sqlite3

from kindnostic.types import Category, ProbeResult, Status

CATEGORY = Category.CRITICAL

_DEFAULT_DB_PATH = "./data/event_ledger.db"


def _compute_checksum(event_id: str, timestamp: str, terminal_id: str,
                      event_type: str, payload: dict, previous_checksum: str) -> str:
    """Recompute SHA-256 checksum matching EventLedger's Event.compute_checksum()."""
    data = {
        "event_id": event_id,
        "timestamp": timestamp,
        "terminal_id": terminal_id,
        "event_type": event_type,
        "payload": payload,
        "previous_checksum": previous_checksum,
    }
    serialized = json.dumps(data, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def probe_hash_chain_integrity() -> ProbeResult:
    """Walk the full event ledger and recompute every SHA-256 hash.

    Any mismatch means the ledger has been tampered with or corrupted.
    """
    db_path = os.environ.get("KINDPOS_DB_PATH", _DEFAULT_DB_PATH)

    if not os.path.exists(db_path):
        return ProbeResult(
            probe_name="hash_chain_integrity",
            category=Category.CRITICAL,
            status=Status.PASS,
            message="Event ledger not found — fresh system, no chain to verify",
            metadata={"db_path": db_path, "events_checked": 0},
        )

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """SELECT sequence_number, event_id, timestamp, terminal_id,
                      event_type, payload, previous_checksum, checksum
               FROM events ORDER BY sequence_number ASC"""
        )

        previous_checksum = ""
        events_checked = 0

        for row in cursor:
            seq, event_id, timestamp, terminal_id, event_type, payload_json, prev_cs, stored_cs = row
            payload = json.loads(payload_json)

            expected_cs = _compute_checksum(
                event_id, timestamp, terminal_id, event_type, payload, previous_checksum
            )

            if stored_cs != expected_cs:
                return ProbeResult(
                    probe_name="hash_chain_integrity",
                    category=Category.CRITICAL,
                    status=Status.FAIL,
                    message=f"Hash mismatch at sequence {seq}: checksum tampered or corrupted",
                    metadata={
                        "failed_sequence": seq,
                        "event_id": event_id,
                        "expected": expected_cs,
                        "stored": stored_cs,
                    },
                )

            if prev_cs != previous_checksum:
                return ProbeResult(
                    probe_name="hash_chain_integrity",
                    category=Category.CRITICAL,
                    status=Status.FAIL,
                    message=f"Chain link broken at sequence {seq}: previous_checksum mismatch",
                    metadata={
                        "failed_sequence": seq,
                        "event_id": event_id,
                        "expected_prev": previous_checksum,
                        "stored_prev": prev_cs,
                    },
                )

            previous_checksum = stored_cs
            events_checked += 1

        return ProbeResult(
            probe_name="hash_chain_integrity",
            category=Category.CRITICAL,
            status=Status.PASS,
            message=None,
            metadata={"events_checked": events_checked, "chain_valid": True},
        )
    finally:
        conn.close()
