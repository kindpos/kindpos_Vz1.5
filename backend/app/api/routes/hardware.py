"""
KINDpos Hardware API
Network scanning, device persistence (hardware_config.db), test print.
MAC-as-identity: IPs change, MACs don't.
"""

import asyncio
import threading
import json
import logging
import os
import socket
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

import aiosqlite
import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...config import settings

logger = logging.getLogger("kindpos.hardware")

router = APIRouter(prefix="/hardware", tags=["hardware"])

# ΓöÇΓöÇ DB path ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
HARDWARE_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    'hardware_config.db'
)

# ΓöÇΓöÇ Port fingerprinting ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
PRINTER_PORTS = [9100, 9101, 9102]
# Dejavoo SPIn ΓÇö default port first, then dedicated fallbacks only
CARD_READER_PORTS = [9000, 8443, 9443]

ALL_SCAN_PORTS = PRINTER_PORTS + CARD_READER_PORTS

# ΓöÇΓöÇ Scan tuning ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
PROBE_TIMEOUT  = 2.5  # TCP connect timeout per port
DIRECT_TIMEOUT = 2.5  # Direct IP probe (user-entered)
PING_TIMEOUT   = 2    # Seconds to wait for broadcast ping / ARP population

# ΓöÇΓöÇ DB bootstrap ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

async def _ensure_db():
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                mac         TEXT PRIMARY KEY,
                ip          TEXT NOT NULL,
                type        TEXT NOT NULL,
                name        TEXT NOT NULL,
                port        INTEGER NOT NULL DEFAULT 9100,
                register_id TEXT NOT NULL DEFAULT '',
                tpn         TEXT NOT NULL DEFAULT '',
                auth_key    TEXT NOT NULL DEFAULT '',
                saved_at    TEXT NOT NULL
            )
        """)
        # Migrate: add columns if missing (existing DBs)
        async with db.execute("PRAGMA table_info(devices)") as cur:
            cols = [row[1] async for row in cur]
        if 'register_id' not in cols:
            await db.execute("ALTER TABLE devices ADD COLUMN register_id TEXT NOT NULL DEFAULT ''")
        if 'tpn' not in cols:
            await db.execute("ALTER TABLE devices ADD COLUMN tpn TEXT NOT NULL DEFAULT ''")
        if 'auth_key' not in cols:
            await db.execute("ALTER TABLE devices ADD COLUMN auth_key TEXT NOT NULL DEFAULT ''")
        if 'categories' not in cols:
            await db.execute("ALTER TABLE devices ADD COLUMN categories TEXT NOT NULL DEFAULT ''")
        await db.commit()

# ΓöÇΓöÇ Models ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

class DeviceRecord(BaseModel):
    mac:  str
    ip:   str
    type: str        # 'kitchen' | 'receipt' | 'card_reader'
    name: str
    port: int = 9100
    register_id: str = ''  # SPIn Register ID for card readers
    tpn: str = ''          # SPIn Terminal Processing Number
    auth_key: str = ''     # SPIn Auth Key for card readers
    categories: str = ''   # Comma-separated category IDs for kitchen printers

class TestRequest(BaseModel):
    mac: str

class TestPrintRequest(BaseModel):
    ip:   str
    port: int = 9100

# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ
#  NETWORK SCANNER ΓÇö ARP-first discovery
#
#  Instead of brute-forcing TCP on 254 hosts (slow, hammers WiFi), we:
#    1. Ping the broadcast address to wake up the ARP cache
#    2. Read `arp -a` to get only the live hosts (usually 3-10)
#    3. TCP probe just those hosts on our specific ports
#
#  This turns 254 ├ù 6 = 1,524 connections into ~5 ├ù 6 = 30.
# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ

def _get_subnet_prefix() -> str:
    """Extract the /24 prefix from settings.default_subnet (e.g. '10.0.0')."""
    raw = settings.default_subnet
    base = raw.split('/')[0]
    return base.rsplit('.', 1)[0]


def _ports_for_type(device_type: Optional[str]) -> list:
    """Return the port list to scan based on device type filter."""
    if device_type == 'card_reader':
        return CARD_READER_PORTS
    elif device_type in ('printer', 'kitchen', 'receipt'):
        return PRINTER_PORTS
    return ALL_SCAN_PORTS


# ΓöÇΓöÇ ARP discovery ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def _ping_broadcast(prefix: str) -> None:
    """
    Ping the broadcast address to populate the OS ARP cache.
    Works cross-platform: tries broadcast ping, then falls back to
    pinging a handful of common addresses.
    """
    broadcast = f"{prefix}.255"
    import platform
    is_win = platform.system() == "Windows"

    # Try broadcast ping first
    try:
        if is_win:
            subprocess.run(
                ['ping', '-n', '1', '-w', str(PING_TIMEOUT * 1000), broadcast],
                timeout=PING_TIMEOUT + 1, capture_output=True,
            )
        else:
            subprocess.run(
                ['ping', '-c', '1', '-W', str(PING_TIMEOUT), '-b', broadcast],
                timeout=PING_TIMEOUT + 1, capture_output=True,
            )
    except Exception:
        pass


def _get_arp_hosts(prefix: str) -> List[dict]:
    """
    Read the OS ARP cache and return all live hosts on our subnet.
    Returns list of {'ip': str, 'mac': str}.
    """
    hosts = []
    try:
        out = subprocess.check_output(
            ['arp', '-a'], timeout=3, stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            # Find IPs on our subnet
            if prefix + '.' not in line:
                continue
            parts = line.split()
            ip = None
            mac = None
            for part in parts:
                # Match IP address
                stripped = part.strip('()')
                if stripped.startswith(prefix + '.') and stripped.count('.') == 3:
                    ip = stripped
                # Match MAC address (xx:xx:xx:xx:xx:xx or xx-xx-xx-xx-xx-xx)
                if len(part) == 17 and (':' in part or '-' in part):
                    mac = part.replace('-', ':').upper()
            if ip and mac:
                # Skip broadcast and incomplete entries
                if mac in ('FF:FF:FF:FF:FF:FF', '00:00:00:00:00:00'):
                    continue
                hosts.append({'ip': ip, 'mac': mac})
    except Exception as e:
        logger.warning(f"ARP cache read failed: {e}")
    return hosts


def _get_mac(ip: str) -> Optional[str]:
    """Best-effort MAC from ARP cache for a single IP."""
    for cmd in (['arp', '-a', ip], ['arp', '-n', ip]):
        try:
            out = subprocess.check_output(
                cmd, timeout=2, stderr=subprocess.DEVNULL
            ).decode()
            for line in out.splitlines():
                if ip in line:
                    for part in line.split():
                        if len(part) == 17 and (':' in part or '-' in part):
                            return part.replace('-', ':').upper()
        except Exception:
            continue
    return None


# ΓöÇΓöÇ Low-level probes ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    """Attempt a TCP connect. Returns True if the port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            return True
    except Exception:
        return False


async def _probe_spin(ip: str, port: int) -> dict:
    """Probe a Dejavoo device via SPIn GET to auto-detect RegisterId and model."""
    xml = "<request><TransType>GetStatus</TransType><RegisterId></RegisterId></request>"
    encoded = urllib.parse.quote(xml, safe='')
    url = f"http://{ip}:{port}/spin/cgi.html?TerminalTransaction={encoded}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.text.strip():
                body = resp.text.strip()
                if "<xmp>" in body:
                    body = body.split("<xmp>", 1)[-1]
                if "</xmp>" in body:
                    body = body.split("</xmp>", 1)[0]
                body = urllib.parse.unquote(body.strip())
                root = ET.fromstring(body)
                return {
                    "register_id": root.findtext("RegisterId") or root.findtext("TerminalId") or "",
                    "serial":      root.findtext("SN") or root.findtext("SerialNo") or "",
                    "model":       root.findtext("Model") or "",
                    "status":      root.findtext("RespMSG") or root.findtext("Message") or "",
                }
    except Exception:
        pass
    return {}


# ΓöÇΓöÇ Host probing ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

async def _probe_host(ip: str, mac: Optional[str], ports: list, timeout: float) -> Optional[dict]:
    """
    Probe a known-live host on all given ports. Collects ALL open ports,
    then classifies the device from the full picture.
    """
    loop = asyncio.get_running_loop()

    async def _try_port(port: int) -> Optional[int]:
        try:
            hit = await asyncio.wait_for(
                loop.run_in_executor(None, _tcp_probe, ip, port, timeout),
                timeout=timeout + 0.2,
            )
            return port if hit else None
        except Exception:
            return None

    results = await asyncio.gather(*[_try_port(p) for p in ports])
    open_ports = [p for p in results if p is not None]

    if not open_ports:
        return None

    # Classify from complete picture ΓÇö printer ports take priority
    printer_hits = [p for p in open_ports if p in PRINTER_PORTS]
    reader_hits = [p for p in open_ports if p in CARD_READER_PORTS]

    if printer_hits:
        dtype = 'printer'
        best_port = printer_hits[0]
        name = 'Thermal Printer'
    elif reader_hits:
        dtype = 'card_reader'
        best_port = reader_hits[0]  # 9000 is first in CARD_READER_PORTS
        name = 'Card Reader'
    else:
        return None

    # Resolve MAC if not provided by ARP discovery
    if not mac:
        await asyncio.sleep(0.05)
        mac = await loop.run_in_executor(None, _get_mac, ip)

    result = {
        'ip':   ip,
        'port': best_port,
        'mac':  mac or f"UNKNOWN-{ip.replace('.', '-')}",
        'type': dtype,
        'name': name,
    }

    # Auto-detect SPIn details for card readers
    if dtype == 'card_reader':
        spin = await _probe_spin(ip, best_port)
        if spin.get('register_id'):
            result['register_id'] = spin['register_id']
        if spin.get('model'):
            result['name'] = spin['model']
        elif spin.get('status'):
            result['name'] = 'Dejavoo'

    return result


# ΓöÇΓöÇ Scan endpoints ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

@router.get("/scan/stream")
async def scan_network_stream(
    ip: Optional[str] = None,
    type: Optional[str] = None,
):
    """
    SSE streaming network scan. Two modes:

    Subnet sweep (default):
        1. Ping broadcast to populate ARP cache
        2. Read ARP table for live hosts on the subnet
        3. TCP probe only those hosts on device-specific ports
        Much faster and more reliable than brute-force scanning.

    Direct IP probe:
        ?ip=10.0.0.19           ΓåÆ single host
        ?ip=10.0.0.19,10.0.0.20 ΓåÆ multiple hosts (comma-separated)

    Optional: ?type=card_reader|printer to filter ports scanned.

    SSE event types:
        start    ΓÇö scan started, includes host count and mode
        device   ΓÇö a device was found
        complete ΓÇö sweep finished
        error    ΓÇö something went wrong
    """
    await _ensure_db()
    ports = _ports_for_type(type)

    # Determine mode: direct IPs vs subnet sweep
    if ip:
        direct_ips = [addr.strip() for addr in ip.split(',') if addr.strip()]
        mode = 'direct'
    else:
        direct_ips = []
        mode = 'sweep'

    # Load saved devices for annotation
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM devices") as cur:
            saved = {row['mac']: dict(row) async for row in cur}

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    def _annotate(device: dict) -> dict:
        if device['mac'] in saved:
            device['saved_name'] = saved[device['mac']]['name']
            device['saved_type'] = saved[device['mac']]['type']
        return device

    async def stream():
        loop = asyncio.get_running_loop()

        try:
            if mode == 'direct':
                # ΓöÇΓöÇ Direct IP probe ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
                yield _sse({'type': 'start', 'total': len(direct_ips), 'mode': 'direct'})

                results = await asyncio.gather(
                    *[_probe_host(h, None, ports, DIRECT_TIMEOUT) for h in direct_ips]
                )
                for r in results:
                    if r is not None:
                        yield _sse({**_annotate(r), 'type': 'device'})

            else:
                # ΓöÇΓöÇ ARP-first subnet sweep ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
                prefix = _get_subnet_prefix()

                # Step 1: Ping broadcast to populate ARP cache
                await loop.run_in_executor(None, _ping_broadcast, prefix)
                # Brief pause to let ARP entries settle
                await asyncio.sleep(0.5)

                # Step 2: Read ARP table for live hosts
                arp_hosts = await loop.run_in_executor(None, _get_arp_hosts, prefix)

                yield _sse({
                    'type': 'start',
                    'total': len(arp_hosts),
                    'mode': 'sweep',
                    'subnet': f"{prefix}.0/24",
                })

                # Step 3: TCP probe hosts in batches of 5, stream as found
                found_ips = set()
                batch_size = 5
                for i in range(0, len(arp_hosts), batch_size):
                    batch = arp_hosts[i:i + batch_size]
                    results = await asyncio.gather(
                        *[_probe_host(h['ip'], h['mac'], ports, PROBE_TIMEOUT)
                          for h in batch]
                    )
                    for r in results:
                        if r is not None:
                            found_ips.add(r['ip'])
                            yield _sse({**_annotate(r), 'type': 'device'})

                # Step 4: Probe saved device IPs not found in ARP sweep
                missed = [
                    s for s in saved.values()
                    if s['ip'] not in found_ips
                ]
                if missed:
                    missed_results = await asyncio.gather(
                        *[_probe_host(s['ip'], s['mac'], ports, PROBE_TIMEOUT)
                          for s in missed]
                    )
                    for r in missed_results:
                        if r is not None:
                            yield _sse({**_annotate(r), 'type': 'device'})

            yield _sse({'type': 'complete'})

        except Exception as e:
            logger.error(f"Scan stream error: {e}")
            yield _sse({'type': 'error', 'message': str(e)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ
#  DEVICE CRUD
# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ

@router.get("/devices")
async def list_devices():
    """Return all saved devices from hardware_config.db."""
    await _ensure_db()
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM devices ORDER BY saved_at") as cur:
            return [dict(row) async for row in cur]


@router.post("/devices")
async def save_device(device: DeviceRecord):
    """Insert or update a device by MAC address."""
    await _ensure_db()
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        await db.execute("""
            INSERT INTO devices (mac, ip, type, name, port, register_id, tpn, auth_key, categories, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                ip          = excluded.ip,
                type        = excluded.type,
                name        = excluded.name,
                port        = excluded.port,
                register_id = excluded.register_id,
                tpn         = excluded.tpn,
                auth_key    = excluded.auth_key,
                categories  = excluded.categories,
                saved_at    = excluded.saved_at
        """, (device.mac.upper(), device.ip, device.type,
              device.name, device.port, device.register_id, device.tpn, device.auth_key,
              device.categories, now))
        await db.commit()
    return {**device.dict(), 'mac': device.mac.upper(), 'saved_at': now}


@router.delete("/devices/{mac}")
async def delete_device(mac: str):
    """Remove a saved device by MAC."""
    await _ensure_db()
    mac = mac.upper()
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        await db.execute("DELETE FROM devices WHERE mac = ?", (mac,))
        await db.commit()
    return {"deleted": mac}

@router.get("/kitchen-printers")
async def list_kitchen_printers():
    """Return kitchen printers with their assigned categories."""
    await _ensure_db()
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices WHERE type = 'kitchen' ORDER BY saved_at"
        ) as cur:
            printers = []
            async for row in cur:
                d = dict(row)
                cats = d.get('categories', '')
                d['categories_list'] = [c.strip() for c in cats.split(',') if c.strip()] if cats else []
                printers.append(d)
            return printers


# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ
#  TEST (by MAC ΓÇö resolves IP from DB)
# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ

@router.post("/test")
async def test_device(req: TestRequest):
    """Test connectivity to a saved device by MAC address."""
    await _ensure_db()
    mac = req.mac.upper()
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices WHERE mac = ?", (mac,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        return {"success": False, "message": f"Device {mac} not saved"}

    dev = dict(row)
    reachable = await asyncio.get_running_loop().run_in_executor(
        None, _tcp_probe, dev['ip'], dev['port'], DIRECT_TIMEOUT
    )
    return {
        "success": reachable,
        "mac": mac,
        "ip": dev['ip'],
        "port": dev['port'],
        "message": "Device reachable" if reachable
                   else f"Cannot connect to {dev['ip']}:{dev['port']}",
    }

# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ
#  TEST PRINT (direct IP ΓÇö used from settings scene device editor)
# ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ

@router.post("/test-print")
async def test_print(request: TestPrintRequest):
    """Send a KINDpos test receipt via raw ESC/POS over TCP."""
    ESC = b'\x1b'; GS = b'\x1d'
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    receipt = bytearray()
    receipt += ESC + b'\x40'                  # init
    receipt += ESC + b'\x61\x01'              # center
    receipt += b'================================\n'
    receipt += ESC + b'\x21\x20' + ESC + b'\x45\x01'
    receipt += b'K I N D p o s\n'
    receipt += ESC + b'\x21\x00' + ESC + b'\x45\x00'
    receipt += b'Nice. Dependable. Yours.\n'
    receipt += b'================================\n\n'
    receipt += ESC + b'\x45\x01' + ESC + b'\x21\x20'
    receipt += b'*** TEST PRINT ***\n'
    receipt += ESC + b'\x21\x00' + ESC + b'\x45\x00' + b'\n'
    receipt += ESC + b'\x61\x00'              # left
    receipt += f'  IP:   {request.ip}\n'.encode()
    receipt += f'  Port: {request.port}\n'.encode()
    receipt += f'  Date: {now}\n'.encode()
    receipt += b'\n' + ESC + b'\x61\x01'
    receipt += b'If you can read this,\nyour printer is ready.\n\n'
    receipt += b'================================\n'
    receipt += ESC + b'\x45\x01' + b'KIND Technologies\n' + ESC + b'\x45\x00'
    receipt += b'================================\n'
    receipt += ESC + b'\x64\x03'              # feed
    receipt += GS  + b'\x56\x00'              # cut

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _send_raw, request.ip, request.port, bytes(receipt)
        )
        return {"success": True,
                "message": f"Test print sent to {request.ip}:{request.port}",
                "timestamp": now}
    except socket.timeout:
        return {"success": False,
                "message": f"Timed out ΓÇö {request.ip}:{request.port} not responding"}
    except ConnectionRefusedError:
        return {"success": False,
                "message": f"Refused ΓÇö {request.ip}:{request.port}"}
    except Exception as e:
        return {"success": False, "message": f"Print failed: {e}"}


def _send_raw(ip: str, port: int, data: bytes):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect((ip, port))
        s.sendall(data)


@router.get("/status")
async def hardware_status():
    return {
        "status": "online",
        "db_path": HARDWARE_DB_PATH,
        "default_subnet": settings.default_subnet,
        "endpoints": [
            "/api/v1/hardware/scan/stream",
            "/api/v1/hardware/devices",
            "/api/v1/hardware/test",
            "/api/v1/hardware/test-print",
            "/api/v1/hardware/test-connection",
            "/api/v1/hardware/status",
        ],
    }


class TestConnectionRequest(BaseModel):
    ip: str
    port: int
    timeout: float = 2.0


@router.post("/test-connection")
async def test_connection(req: TestConnectionRequest):
    """Test raw TCP connectivity to an IP:port."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(req.timeout)
        s.connect((req.ip, req.port))
        s.close()
        status = "online"
    except (socket.timeout, ConnectionRefusedError, OSError):
        status = "unreachable"
    return {"ip": req.ip, "port": req.port, "status": status}

# ── Overseer: Printer Discovery (SSE) ────────────────────────────────────────

from app.scanner.printer_detector import PrinterDiscovery

class ScanRequest(BaseModel):
    network: Optional[str] = None
    timeout: Optional[float] = None


def _run_scan_in_thread(queue: asyncio.Queue, loop, network: str):
    scanner = PrinterDiscovery()

    def on_progress(event_type: str, data: dict):
        event = {"type": event_type, **data}
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    scanner.on_progress = on_progress

    try:
        printers = scanner.scan_network(network, methods=["port_scan"])
        for printer in printers:
            config = printer.to_printer_config_dict()
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "printer_config", **config}), loop)
    except Exception as e:
        asyncio.run_coroutine_threadsafe(
            queue.put({"type": "error", "message": f"Scan failed: {str(e)}"}), loop)

    asyncio.run_coroutine_threadsafe(queue.put({"type": "__DONE__"}), loop)


@router.post("/discover-printers")
async def discover_printers(request: ScanRequest = ScanRequest()):
    network = request.network or settings.default_subnet

    async def discovery_stream():
        queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        thread = threading.Thread(
            target=_run_scan_in_thread, args=(queue, loop, network), daemon=True)
        thread.start()
        while True:
            event = await queue.get()
            if event.get("type") == "__DONE__":
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        discovery_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )

