"""
KINDnostic Support Codes Tests
===============================
Validates support code format, known probe mappings, and fallback behavior.
"""

import re
from datetime import datetime

from kindnostic.support_codes import generate_support_code, register_probe


def test_code_format_matches_pattern():
    code = generate_support_code("hash_chain_integrity")
    assert re.match(r"^KN-[A-Z]{2}-\d{4}$", code)


def test_known_probe_codes():
    assert generate_support_code("hash_chain_integrity").startswith("KN-HC-")
    assert generate_support_code("precision_gate").startswith("KN-PG-")
    assert generate_support_code("database_integrity").startswith("KN-DI-")
    assert generate_support_code("database_writable").startswith("KN-DW-")
    assert generate_support_code("schema_version").startswith("KN-SV-")
    assert generate_support_code("receipt_printer_reachable").startswith("KN-RP-")
    assert generate_support_code("kitchen_printer_reachable").startswith("KN-KP-")
    assert generate_support_code("ssd_health").startswith("KN-SD-")
    assert generate_support_code("clock_sync").startswith("KN-CK-")
    assert generate_support_code("display_resolution").startswith("KN-DR-")
    assert generate_support_code("dummy").startswith("KN-DU-")


def test_unknown_probe_falls_back():
    code = generate_support_code("mystery_probe")
    assert code.startswith("KN-MY-")


def test_mmdd_matches_today():
    code = generate_support_code("dummy")
    mmdd = code.split("-")[2]
    assert mmdd == datetime.now().strftime("%m%d")


def test_register_custom_probe():
    register_probe("custom_check", "CC")
    code = generate_support_code("custom_check")
    assert code.startswith("KN-CC-")
