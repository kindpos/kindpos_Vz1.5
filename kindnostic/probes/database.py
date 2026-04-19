"""Database probes — integrity check, writable test, and schema version verification."""

import os
import sqlite3
from typing import Optional

from kindnostic.types import Category, ProbeResult, Status

CATEGORY = Category.CRITICAL

_DEFAULT_LEDGER_PATH = "./data/event_ledger.db"
_DEFAULT_HW_PATH = "./hardware_config.db"
_DEFAULT_DIAG_PATH = "./data/diagnostic_boot.db"

# Expected tables per database — used for schema version check
_EXPECTED_SCHEMAS = {
    "event_ledger": {
        "tables": {"events"},
        "version": 1,
    },
    "hardware_config": {
        "tables": {"devices"},
        "version": 1,
    },
    "diagnostic_boot": {
        "tables": {"boot_results", "boot_summary"},
        "version": 1,
    },
}


def _get_db_paths() -> list[tuple[str, str]]:
    """Return list of (label, path) for all databases to check."""
    return [
        ("event_ledger", os.environ.get("KINDPOS_DB_PATH", _DEFAULT_LEDGER_PATH)),
        ("hardware_config", os.environ.get("KINDPOS_HW_DB_PATH", _DEFAULT_HW_PATH)),
        ("diagnostic_boot", os.environ.get("KINDPOS_DIAG_DB_PATH", _DEFAULT_DIAG_PATH)),
    ]


def probe_database_integrity() -> ProbeResult:
    """Run PRAGMA integrity_check on all SQLite databases."""
    db_paths = _get_db_paths()
    checked = []
    failures = []

    for label, path in db_paths:
        if not os.path.exists(path):
            checked.append({"db": label, "status": "skipped", "reason": "not found"})
            continue

        try:
            conn = sqlite3.connect(path)
            try:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if result == "ok":
                    checked.append({"db": label, "status": "ok"})
                else:
                    failures.append({"db": label, "result": result})
            finally:
                conn.close()
        except Exception as exc:
            failures.append({"db": label, "error": str(exc)})

    if failures:
        return ProbeResult(
            probe_name="database_integrity",
            category=Category.CRITICAL,
            status=Status.FAIL,
            message=f"Integrity check failed for: {', '.join(f['db'] for f in failures)}",
            metadata={"checked": checked, "failures": failures},
        )

    return ProbeResult(
        probe_name="database_integrity",
        category=Category.CRITICAL,
        status=Status.PASS,
        message=None,
        metadata={"checked": checked},
    )


def probe_database_writable() -> ProbeResult:
    """Attempt a write + rollback on each database to verify write access."""
    db_paths = _get_db_paths()
    checked = []
    failures = []

    for label, path in db_paths:
        if not os.path.exists(path):
            checked.append({"db": label, "status": "skipped", "reason": "not found"})
            continue

        try:
            conn = sqlite3.connect(path)
            try:
                conn.execute("SAVEPOINT write_test")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS _kindnostic_write_test (id INTEGER)"
                )
                conn.execute("INSERT INTO _kindnostic_write_test VALUES (1)")
                conn.execute("ROLLBACK TO write_test")
                conn.execute("RELEASE write_test")
                checked.append({"db": label, "status": "writable"})
            finally:
                conn.close()
        except Exception as exc:
            failures.append({"db": label, "error": str(exc)})

    if failures:
        return ProbeResult(
            probe_name="database_writable",
            category=Category.CRITICAL,
            status=Status.FAIL,
            message=f"Write test failed for: {', '.join(f['db'] for f in failures)}",
            metadata={"checked": checked, "failures": failures},
        )

    return ProbeResult(
        probe_name="database_writable",
        category=Category.CRITICAL,
        status=Status.PASS,
        message=None,
        metadata={"checked": checked},
    )


def probe_schema_version() -> ProbeResult:
    """Verify each DB has the expected tables (schema version check)."""
    db_paths = _get_db_paths()
    checked = []
    failures = []

    for label, path in db_paths:
        if not os.path.exists(path):
            checked.append({"db": label, "status": "skipped", "reason": "not found"})
            continue

        expected = _EXPECTED_SCHEMAS.get(label)
        if not expected:
            checked.append({"db": label, "status": "skipped", "reason": "no schema defined"})
            continue

        try:
            conn = sqlite3.connect(path)
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                actual_tables = {row[0] for row in rows}
                missing = expected["tables"] - actual_tables

                if missing:
                    failures.append({
                        "db": label,
                        "missing_tables": sorted(missing),
                        "expected_version": expected["version"],
                    })
                else:
                    checked.append({
                        "db": label,
                        "status": "ok",
                        "tables": sorted(actual_tables),
                        "version": expected["version"],
                    })
            finally:
                conn.close()
        except Exception as exc:
            failures.append({"db": label, "error": str(exc)})

    if failures:
        return ProbeResult(
            probe_name="schema_version",
            category=Category.CRITICAL,
            status=Status.FAIL,
            message=f"Schema mismatch for: {', '.join(f['db'] for f in failures)}",
            metadata={"checked": checked, "failures": failures},
        )

    return ProbeResult(
        probe_name="schema_version",
        category=Category.CRITICAL,
        status=Status.PASS,
        message=None,
        metadata={"checked": checked},
    )
