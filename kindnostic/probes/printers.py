"""Printer reachability probes — TCP connect to receipt and kitchen printers."""

import os
import socket
import sqlite3
from typing import Optional

from kindnostic.types import Category, ProbeResult, Status

CATEGORY = Category.HIGH

_DEFAULT_HW_DB_PATH = "./hardware_config.db"
_CONNECT_TIMEOUT = 2.0


def _get_printer_ip(device_type: str, name_hint: str) -> Optional[tuple[str, int]]:
    """Look up a printer's IP and port from hardware_config.db.

    Searches for devices matching the type and optional name hint.
    Returns (ip, port) or None if not found.
    """
    db_path = os.environ.get("KINDPOS_HW_DB_PATH", _DEFAULT_HW_DB_PATH)

    if not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path)
    try:
        # Look for printers — try name hint first, fall back to type match
        row = conn.execute(
            "SELECT ip, port FROM devices WHERE type = ? AND LOWER(name) LIKE ? LIMIT 1",
            (device_type, f"%{name_hint.lower()}%"),
        ).fetchone()

        if not row:
            row = conn.execute(
                "SELECT ip, port FROM devices WHERE type = ? LIMIT 1",
                (device_type,),
            ).fetchone()

        return (row[0], row[1]) if row else None
    finally:
        conn.close()


def _check_tcp_reachable(ip: str, port: int, timeout: float = _CONNECT_TIMEOUT) -> bool:
    """Attempt a TCP connection. Returns True if reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.close()
        return True
    except (socket.timeout, socket.error, OSError):
        return False


def probe_receipt_printer_reachable() -> ProbeResult:
    """TCP connect to receipt printer IP:port from hardware_config.db."""
    target = _get_printer_ip("printer", "receipt")

    if target is None:
        return ProbeResult(
            probe_name="receipt_printer_reachable",
            category=Category.HIGH,
            status=Status.PASS,
            message="No receipt printer configured in hardware_config.db",
            metadata={"configured": False},
        )

    ip, port = target
    reachable = _check_tcp_reachable(ip, port)

    if not reachable:
        return ProbeResult(
            probe_name="receipt_printer_reachable",
            category=Category.HIGH,
            status=Status.WARN,
            message=f"Receipt printer unreachable at {ip}:{port}",
            metadata={"ip": ip, "port": port, "reachable": False},
        )

    return ProbeResult(
        probe_name="receipt_printer_reachable",
        category=Category.HIGH,
        status=Status.PASS,
        message=None,
        metadata={"ip": ip, "port": port, "reachable": True},
    )


def probe_kitchen_printer_reachable() -> ProbeResult:
    """TCP connect to kitchen printer IP:port from hardware_config.db."""
    target = _get_printer_ip("printer", "kitchen")

    if target is None:
        return ProbeResult(
            probe_name="kitchen_printer_reachable",
            category=Category.HIGH,
            status=Status.PASS,
            message="No kitchen printer configured in hardware_config.db",
            metadata={"configured": False},
        )

    ip, port = target
    reachable = _check_tcp_reachable(ip, port)

    if not reachable:
        return ProbeResult(
            probe_name="kitchen_printer_reachable",
            category=Category.HIGH,
            status=Status.WARN,
            message=f"Kitchen printer unreachable at {ip}:{port}",
            metadata={"ip": ip, "port": port, "reachable": False},
        )

    return ProbeResult(
        probe_name="kitchen_printer_reachable",
        category=Category.HIGH,
        status=Status.PASS,
        message=None,
        metadata={"ip": ip, "port": port, "reachable": True},
    )
