"""
KINDnostic Storage Tests
========================
Validates BootStorage: table creation, record_result, record_summary,
get_last_boot_summary, WAL mode, and data persistence.
"""

from kindnostic.storage import BootStorage


def test_tables_created_on_connect(tmp_path):
    db = str(tmp_path / "test.db")
    with BootStorage(db) as storage:
        tables = storage._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {row["name"] for row in tables}
    assert "boot_results" in names
    assert "boot_summary" in names


def test_wal_mode_enabled(tmp_path):
    db = str(tmp_path / "test.db")
    with BootStorage(db) as storage:
        mode = storage._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_record_result_inserts(tmp_path):
    db = str(tmp_path / "test.db")
    with BootStorage(db) as storage:
        storage.record_result(
            boot_id="boot-1",
            probe_name="dummy",
            category="LOW",
            status="PASS",
            duration_ms=42,
            message=None,
            metadata={"key": "val"},
        )
        rows = storage._conn.execute("SELECT * FROM boot_results").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["boot_id"] == "boot-1"
    assert row["probe_name"] == "dummy"
    assert row["status"] == "PASS"
    assert row["duration_ms"] == 42


def test_record_summary_and_get_last(tmp_path):
    db = str(tmp_path / "test.db")
    with BootStorage(db) as storage:
        storage.record_summary(
            boot_id="boot-1",
            total_probes=3,
            passed=2,
            warned=1,
            failed=0,
            duration_ms=500,
            outcome="READY",
        )
        summary = storage.get_last_boot_summary()
    assert summary is not None
    assert summary["boot_id"] == "boot-1"
    assert summary["total_probes"] == 3
    assert summary["passed"] == 2
    assert summary["warned"] == 1
    assert summary["failed"] == 0
    assert summary["outcome"] == "READY"


def test_get_last_summary_returns_most_recent(tmp_path):
    db = str(tmp_path / "test.db")
    with BootStorage(db) as storage:
        storage.record_summary("boot-old", 1, 1, 0, 0, 100, "READY")
        storage.record_summary("boot-new", 2, 1, 0, 1, 200, "BLOCKED")
        summary = storage.get_last_boot_summary()
    assert summary["boot_id"] == "boot-new"
    assert summary["outcome"] == "BLOCKED"


def test_get_last_summary_empty_db(tmp_path):
    db = str(tmp_path / "test.db")
    with BootStorage(db) as storage:
        assert storage.get_last_boot_summary() is None


def test_data_survives_reconnect(tmp_path):
    db = str(tmp_path / "test.db")
    with BootStorage(db) as storage:
        storage.record_summary("boot-1", 1, 1, 0, 0, 50, "READY")

    with BootStorage(db) as storage:
        summary = storage.get_last_boot_summary()
    assert summary is not None
    assert summary["boot_id"] == "boot-1"
