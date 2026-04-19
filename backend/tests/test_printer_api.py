"""
KINDpos Hardware Discovery API Tests
=====================================
Tests for the /api/v1/hardware/* endpoints:
    - GET  /scan/stream   — SSE streaming network scan
    - POST /test          — test connectivity by MAC
    - POST /test-print    — send test print by IP
    - POST /devices       — persist device config
    - GET  /devices       — list saved devices
    - DELETE /devices/:mac — remove a saved device
    - GET  /status        — hardware subsystem status
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from app.core.event_ledger import EventLedger
from app.api import dependencies as deps

TEST_DB = Path("./data/test_printer_api.db")


@pytest_asyncio.fixture
async def ledger():
    """Fresh EventLedger per test."""
    if TEST_DB.exists():
        os.remove(TEST_DB)
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def client(ledger):
    """AsyncClient wired to the real FastAPI app with a test ledger."""
    from app.main import app
    from app.api.routes.hardware import HARDWARE_DB_PATH

    async def _override_ledger():
        return ledger

    app.dependency_overrides[deps.get_ledger] = _override_ledger

    # Clean hardware DB for test isolation
    if os.path.exists(HARDWARE_DB_PATH):
        os.remove(HARDWARE_DB_PATH)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

    if os.path.exists(HARDWARE_DB_PATH):
        os.remove(HARDWARE_DB_PATH)


# ── GET /api/v1/hardware/scan/stream ─────────────────────────

import json


def _parse_sse(text: str) -> list:
    """Parse SSE text into a list of JSON objects."""
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


class TestHardwareScan:
    """Tests for GET /api/v1/hardware/scan/stream (SSE)"""

    async def test_scan_stream_emits_start_and_complete(self, client):
        """SSE stream emits start and complete events."""
        resp = await client.get("/api/v1/hardware/scan/stream", params={"ip": "192.0.2.1"})
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        types = [e['type'] for e in events]
        assert 'start' in types
        assert 'complete' in types

    async def test_scan_stream_start_has_mode(self, client):
        """Start event includes the scan mode."""
        resp = await client.get("/api/v1/hardware/scan/stream", params={"ip": "192.0.2.1"})
        events = _parse_sse(resp.text)
        start = next(e for e in events if e['type'] == 'start')
        assert start['mode'] == 'direct'

    async def test_scan_stream_direct_multiple_ips(self, client):
        """Direct IP mode accepts comma-separated addresses."""
        resp = await client.get("/api/v1/hardware/scan/stream", params={"ip": "192.0.2.1,192.0.2.2"})
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        start = next(e for e in events if e['type'] == 'start')
        assert start['total'] == 2
        assert start['mode'] == 'direct'

    async def test_scan_stream_sweep_mode(self, client):
        """Without ?ip, runs in sweep mode via ARP discovery."""
        resp = await client.get("/api/v1/hardware/scan/stream", params={"type": "card_reader"})
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        start = next(e for e in events if e['type'] == 'start')
        assert start['mode'] == 'sweep'
        # total = number of ARP-discovered hosts (0 in test env, varies on real LAN)
        assert isinstance(start['total'], int)


# ── POST /api/v1/hardware/test ────────────────────────


class TestHardwareTest:
    """Tests for POST /api/v1/hardware/test (by MAC)"""

    async def test_test_requires_mac(self, client):
        """Returns 422 without mac field."""
        resp = await client.post("/api/v1/hardware/test", json={})
        assert resp.status_code == 422

    async def test_test_unknown_mac_returns_not_saved(self, client):
        """Returns success=false when MAC isn't in the device DB."""
        resp = await client.post("/api/v1/hardware/test", json={
            "mac": "00:11:22:33:44:55"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "not saved" in data["message"].lower()

    async def test_test_saved_device_unreachable(self, client):
        """After saving a device, test returns success=false if unreachable."""
        # Save a device first
        await client.post("/api/v1/hardware/devices", json={
            "mac": "AA:BB:CC:DD:EE:FF",
            "ip": "192.0.2.1",
            "type": "printer",
            "name": "Test Printer",
            "port": 9100,
        })
        # Test it — unreachable IP
        resp = await client.post("/api/v1/hardware/test", json={
            "mac": "AA:BB:CC:DD:EE:FF"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["mac"] == "AA:BB:CC:DD:EE:FF"


# ── POST /api/v1/hardware/test-print ─────────────────


class TestHardwareTestPrint:
    """Tests for POST /api/v1/hardware/test-print (by IP)"""

    async def test_test_print_requires_ip(self, client):
        """Returns 422 without ip field."""
        resp = await client.post("/api/v1/hardware/test-print", json={})
        assert resp.status_code == 422

    async def test_test_print_unreachable(self, client):
        """Returns success=false for unreachable IP."""
        resp = await client.post("/api/v1/hardware/test-print", json={
            "ip": "192.0.2.1", "port": 9100
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


# ── POST /api/v1/hardware/devices ─────────────────────


class TestDeviceSave:
    """Tests for POST /api/v1/hardware/devices"""

    async def test_save_requires_fields(self, client):
        """Returns 422 without required fields."""
        resp = await client.post("/api/v1/hardware/devices", json={})
        assert resp.status_code == 422

    async def test_save_returns_device(self, client):
        """Response echoes back the saved device with uppercase MAC."""
        resp = await client.post("/api/v1/hardware/devices", json={
            "mac": "aa:bb:cc:dd:ee:ff",
            "ip": "192.168.1.100",
            "type": "printer",
            "name": "Kitchen",
            "port": 9100,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mac"] == "AA:BB:CC:DD:EE:FF"
        assert data["name"] == "Kitchen"
        assert "saved_at" in data

    async def test_save_upserts_by_mac(self, client):
        """Saving same MAC twice updates rather than duplicating."""
        payload = {
            "mac": "11:22:33:44:55:66",
            "ip": "192.168.1.50",
            "type": "printer",
            "name": "Bar Printer",
            "port": 9100,
        }
        await client.post("/api/v1/hardware/devices", json=payload)

        # Update name
        payload["name"] = "Bar Printer (updated)"
        await client.post("/api/v1/hardware/devices", json=payload)

        # Should have exactly 1 device
        resp = await client.get("/api/v1/hardware/devices")
        devices = resp.json()
        assert len(devices) == 1
        assert devices[0]["name"] == "Bar Printer (updated)"


# ── GET /api/v1/hardware/devices ──────────────────────


class TestDeviceList:
    """Tests for GET /api/v1/hardware/devices"""

    async def test_devices_returns_list(self, client):
        """Response is a JSON array."""
        resp = await client.get("/api/v1/hardware/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_devices_empty_when_none_saved(self, client):
        """Returns empty list when no devices saved."""
        resp = await client.get("/api/v1/hardware/devices")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_saved_devices_have_required_fields(self, client):
        """Each saved device has mac, ip, type, name, port, saved_at."""
        await client.post("/api/v1/hardware/devices", json={
            "mac": "AA:BB:CC:DD:EE:FF",
            "ip": "192.168.1.50",
            "type": "receipt",
            "name": "Receipt Printer",
            "port": 9100,
        })

        resp = await client.get("/api/v1/hardware/devices")
        data = resp.json()
        assert len(data) == 1

        d = data[0]
        assert d["mac"] == "AA:BB:CC:DD:EE:FF"
        assert d["name"] == "Receipt Printer"
        assert d["ip"] == "192.168.1.50"
        assert d["port"] == 9100
        assert d["type"] == "receipt"
        assert "saved_at" in d


# ── DELETE /api/v1/hardware/devices/:mac ──────────────


class TestDeviceDelete:
    """Tests for DELETE /api/v1/hardware/devices/:mac"""

    async def test_delete_removes_device(self, client):
        """After delete, device no longer appears in list."""
        await client.post("/api/v1/hardware/devices", json={
            "mac": "DE:AD:BE:EF:00:01",
            "ip": "192.168.1.200",
            "type": "printer",
            "name": "Old Printer",
            "port": 9100,
        })
        resp = await client.delete("/api/v1/hardware/devices/DE:AD:BE:EF:00:01")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "DE:AD:BE:EF:00:01"

        devices = (await client.get("/api/v1/hardware/devices")).json()
        assert len(devices) == 0


# ── GET /api/v1/hardware/status ───────────────────────


class TestHardwareStatus:
    """Tests for GET /api/v1/hardware/status"""

    async def test_status_returns_online(self, client):
        """Status endpoint returns status and subnet info."""
        resp = await client.get("/api/v1/hardware/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"
        assert "default_subnet" in data
