"""Precision gate probe — verifies no floating-point drift on 2dp monetary values."""

import json
import os
import sqlite3
from decimal import Decimal

from kindnostic.types import Category, ProbeResult, Status

CATEGORY = Category.CRITICAL

_DEFAULT_DB_PATH = "./data/event_ledger.db"

# Boundary values that stress IEEE 754 floating-point
_TEST_VALUES = [
    Decimal("0.01"),
    Decimal("0.10"),
    Decimal("9.99"),
    Decimal("19.95"),
    Decimal("99.99"),
    Decimal("100.00"),
    Decimal("999.99"),
    Decimal("0.30"),   # 0.1 + 0.2 — classic float trap
]


def probe_precision_gate() -> ProbeResult:
    """Write 2dp boundary test values, read them back, verify no drift.

    Uses a temporary table that is rolled back after verification.
    """
    db_path = os.environ.get("KINDPOS_DB_PATH", _DEFAULT_DB_PATH)

    if not os.path.exists(db_path):
        return ProbeResult(
            probe_name="precision_gate",
            category=Category.CRITICAL,
            status=Status.PASS,
            message="Event ledger not found — fresh system, precision gate skipped",
            metadata={"db_path": db_path},
        )

    conn = sqlite3.connect(db_path)
    try:
        # Use a savepoint so we can cleanly roll back
        conn.execute("SAVEPOINT precision_test")

        conn.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _precision_test (
                id INTEGER PRIMARY KEY,
                amount_text TEXT NOT NULL,
                amount_real REAL NOT NULL
            )
        """)

        # Write test values as both TEXT (exact) and REAL (potentially lossy)
        for i, val in enumerate(_TEST_VALUES):
            conn.execute(
                "INSERT INTO _precision_test (id, amount_text, amount_real) VALUES (?, ?, ?)",
                (i, str(val), float(val)),
            )

        # Read back and verify
        drift_found = []
        cursor = conn.execute("SELECT id, amount_text, amount_real FROM _precision_test")
        for row_id, text_val, real_val in cursor:
            expected = Decimal(text_val)
            # Round-trip through REAL and back to Decimal
            actual = Decimal(str(real_val)).quantize(Decimal("0.01"))
            if actual != expected:
                drift_found.append({
                    "test_id": row_id,
                    "expected": str(expected),
                    "actual": str(actual),
                    "raw_real": real_val,
                })

        # Also verify JSON round-trip (payload storage uses JSON)
        json_drift = []
        for val in _TEST_VALUES:
            payload = {"amount": float(val)}
            serialized = json.dumps(payload)
            deserialized = json.loads(serialized)
            recovered = Decimal(str(deserialized["amount"])).quantize(Decimal("0.01"))
            if recovered != val:
                json_drift.append({
                    "expected": str(val),
                    "recovered": str(recovered),
                })

        conn.execute("ROLLBACK TO precision_test")
        conn.execute("RELEASE precision_test")

        if drift_found or json_drift:
            return ProbeResult(
                probe_name="precision_gate",
                category=Category.CRITICAL,
                status=Status.FAIL,
                message=f"Floating-point drift detected: {len(drift_found)} SQL, {len(json_drift)} JSON",
                metadata={"sql_drift": drift_found, "json_drift": json_drift},
            )

        return ProbeResult(
            probe_name="precision_gate",
            category=Category.CRITICAL,
            status=Status.PASS,
            message=None,
            metadata={"values_tested": len(_TEST_VALUES), "drift_detected": False},
        )
    finally:
        conn.close()
