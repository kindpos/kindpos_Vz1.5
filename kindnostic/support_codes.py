"""KINDnostic support code generation — maps probe names to KN-XX-MMDD codes."""

from datetime import datetime


# ─── Known probe → two-letter code mapping ───────────────────
_PROBE_CODE_MAP: dict[str, str] = {
    "hash_chain_integrity": "HC",
    "precision_gate": "PG",
    "database_integrity": "DI",
    "database_writable": "DW",
    "schema_version": "SV",
    "receipt_printer_reachable": "RP",
    "kitchen_printer_reachable": "KP",
    "ssd_health": "SD",
    "clock_sync": "CK",
    "display_resolution": "DR",
    "entomology_heartbeat": "EH",
    "network_interface": "NI",
    "last_boot_result": "LB",
    "uptime_since_last_close": "UP",
    "dummy": "DU",
}


def register_probe(probe_name: str, code: str) -> None:
    """Register a custom two-letter code for a probe at runtime."""
    _PROBE_CODE_MAP[probe_name] = code.upper()[:2]


def generate_support_code(probe_name: str) -> str:
    """Return a support code in KN-XX-MMDD format.

    Uses the registered two-letter code for known probes,
    or falls back to the first two characters uppercased.
    """
    code = _PROBE_CODE_MAP.get(probe_name, probe_name[:2].upper())
    mmdd = datetime.now().strftime("%m%d")
    return f"KN-{code}-{mmdd}"
