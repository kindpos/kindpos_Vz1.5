"""
KINDpos Printer Discovery - Core Module
=========================================
Nice. Dependable. Yours.

Discovers ESC/POS printers on restaurant networks and collects
device information for KINDpos deployment. Brand-agnostic,
protocol-level, event-sourced.

The DiscoveredPrinter data model is designed to feed directly
into KINDpos PrinterConfig — no translation layer needed.

    Discovery fills in:  Network identity + device info
    Operator fills in:   Role, location, friendly name (via Overseer GUI)
    Export produces:     PrinterConfig-compatible JSON for terminal import

Data flow:
    Overseer scans network
        → DiscoveredPrinter objects created
        → Operator labels in GUI (role, location)
        → Export to PrinterConfig JSON
        → KINDpos terminal imports
        → PrinterManager.register_printer(discovered_via="port_scan")
        → Event Ledger records PRINTER_REGISTERED

File location: scanner/printer_detector.py
"""

import logging
import platform
import re
import socket
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Callable

logger = logging.getLogger("kindpos.overseer.scanner")

# Platform detection — Windows vs Linux/macOS
# Affects ping flags, ARP commands, and nmap behavior
IS_WINDOWS = platform.system().lower() == "windows"


# =============================================================
# SECTION 1: DiscoveredPrinter Data Model
# =============================================================
#
# Four field groups with clear ownership:
#
#   Group A — Network Identity (auto-discovered)
#   Group B — Device Information (enriched in later phases)
#   Group C — Operator-Assigned (set in Overseer GUI)
#   Group D — Discovery Metadata (auto-generated)
#
# =============================================================


@dataclass
class DiscoveredPrinter:
    """
    Represents a printer discovered on the network.

    Designed to bridge the gap between raw network discovery
    and KINDpos PrinterConfig. The scanner fills in what it
    can find automatically. The operator fills in the rest
    through the Overseer GUI. The export maps cleanly to
    PrinterConfig for terminal import.

    PrinterConfig mapping:
        ip_address      -> connection_string (as "tcp://ip:port")
        friendly_name   -> name
        device_subtype  -> role
        location_notes  -> location_tag
        manufacturer    -> (metadata)
        model           -> (metadata)
        serial_number   -> (metadata)
    """

    # ---------------------------------------------------------
    # Group A: Network Identity (auto-discovered)
    # ---------------------------------------------------------
    ip_address: str                              # e.g., "10.0.0.186"
    mac_address: str = "unknown"                 # e.g., "00:53:53:FA:54:3E"
    hostname: Optional[str] = None               # e.g., "volcora-wrp208326"
    open_ports: List[int] = field(default_factory=list)  # e.g., [9100]
    response_time_ms: float = 0.0                # Network latency

    # ---------------------------------------------------------
    # Group B: Device Information (enriched in later phases)
    # ---------------------------------------------------------
    manufacturer: Optional[str] = None           # e.g., "Volcora", "Epson", "Star"
    model: Optional[str] = None                  # e.g., "VOC-V-WRP2-A1B"
    serial_number: Optional[str] = None          # e.g., "WRP208326"
    protocol: str = "escpos"                     # "escpos", "ipp", "lpd"
    firmware_version: Optional[str] = None       # e.g., "2.11NRD_hwv21"
    services: List[str] = field(default_factory=list)  # mDNS services

    # ---------------------------------------------------------
    # Group C: Operator-Assigned (set in Overseer GUI)
    # Maps directly to PrinterConfig fields
    # ---------------------------------------------------------
    friendly_name: Optional[str] = None          # -> PrinterConfig.name
    device_subtype: Optional[str] = None         # -> PrinterConfig.role
    location_notes: str = ""                     # -> PrinterConfig.location_tag

    # ---------------------------------------------------------
    # Group D: Discovery Metadata (auto-generated)
    # ---------------------------------------------------------
    discovery_method: str = "port_scan"          # "port_scan", "mdns", "snmp", "usb"
    discovered_at: datetime = field(default_factory=datetime.now)
    scan_id: str = ""                            # Links to scan session
    online_status: bool = True                   # Reachable at discovery time

    def to_printer_config_dict(self) -> dict:
        """
        Export as a dictionary compatible with KINDpos PrinterConfig.

        This is the bridge between discovery and deployment.
        The Overseer GUI calls this after the operator has
        labeled the printer (role, location, friendly name).
        """
        port = 9100 if 9100 in self.open_ports else (self.open_ports[0] if self.open_ports else 9100)
        connection_string = f"tcp://{self.ip_address}:{port}"

        return {
            "printer_id": f"printer-{self.device_subtype or 'unknown'}-{self.mac_address.replace(':', '')[-6:].lower()}",
            "name": self.friendly_name or f"Printer at {self.ip_address}",
            "printer_type": self._infer_printer_type(),
            "role": self.device_subtype or "receipt",
            "connection_string": connection_string,
            "location_tag": self.location_notes,
            "discovered_via": self.discovery_method,
            "_discovery_metadata": {
                "ip_address": self.ip_address,
                "mac_address": self.mac_address,
                "manufacturer": self.manufacturer,
                "model": self.model,
                "serial_number": self.serial_number,
                "firmware_version": self.firmware_version,
                "discovered_at": self.discovered_at.isoformat(),
                "scan_id": self.scan_id,
            },
        }

    def _infer_printer_type(self) -> str:
        """Infer thermal vs impact from device info."""
        if self.device_subtype == "kitchen":
            return "impact"
        return "thermal"

    def __str__(self) -> str:
        """Human-readable summary for CLI and logging."""
        name = self.friendly_name or self.manufacturer or "Unknown"
        model_str = f" {self.model}" if self.model else ""
        return (
            f"{name}{model_str} at {self.ip_address} "
            f"(MAC: {self.mac_address}, "
            f"ports: {self.open_ports}, "
            f"{self.response_time_ms:.1f}ms)"
        )


# =============================================================
# SECTION 2: PrinterDiscovery Orchestrator
# =============================================================


class PrinterDiscovery:
    """
    Main printer discovery orchestrator.

    Scans restaurant networks for ESC/POS printers using
    multiple discovery methods. Results are deduplicated
    and returned as DiscoveredPrinter objects.

    Usage:
        scanner = PrinterDiscovery()
        printers = scanner.scan_network("10.0.0.0/24", methods=["port_scan"])

        for printer in printers:
            config = printer.to_printer_config_dict()

    SSE Streaming (for Overseer GUI):
        scanner = PrinterDiscovery()
        scanner.on_progress = my_callback
        printers = scanner.scan_network("10.0.0.0/24")
    """

    # Ports that indicate a network printer
    PRINTER_PORTS = {
        9100: "escpos",    # ESC/POS raw TCP socket (PRIMARY)
        515:  "lpd",       # LPD/LPR line printer daemon
        631:  "ipp",       # IPP/CUPS protocol
    }

    def __init__(self):
        """Initialize the discovery orchestrator."""
        self.discovered_printers: List[DiscoveredPrinter] = []
        self.scan_id: str = self._generate_scan_id()
        self._scan_start: Optional[datetime] = None
        self._scan_end: Optional[datetime] = None

        # Progress callback for SSE streaming to Overseer GUI
        # Signature: callback(event_type: str, data: dict)
        self.on_progress: Optional[Callable] = None

        logger.info(f"[SCANNER] PrinterDiscovery initialized (scan_id={self.scan_id})")

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def scan_network(
        self,
        network_cidr: str,
        methods: Optional[List[str]] = None,
    ) -> List[DiscoveredPrinter]:
        """
        Scan network for printers using specified methods.

        Args:
            network_cidr: Network to scan (e.g., "10.0.0.0/24")
            methods: Discovery methods to use. Options:
                ["port_scan", "mdns", "snmp", "usb"]
                If None, uses ["port_scan"].

        Returns:
            List of discovered printers, deduplicated by IP.
        """
        if methods is None:
            methods = ["port_scan"]

        self._scan_start = datetime.now()
        results = []

        logger.info(
            f"[SCANNER] Starting scan on {network_cidr} "
            f"(methods: {methods}, scan_id: {self.scan_id})"
        )

        self._emit("scan_start", {
            "network": network_cidr,
            "methods": methods,
            "scan_id": self.scan_id,
        })

        if "port_scan" in methods:
            results.extend(self._port_scan_discovery(network_cidr))

        if "mdns" in methods:
            results.extend(self._mdns_discovery())

        if "snmp" in methods:
            results.extend(self._snmp_discovery(network_cidr))

        if "usb" in methods:
            results.extend(self._usb_discovery())

        # Deduplicate and store
        unique_printers = self._deduplicate(results)
        self.discovered_printers = unique_printers
        self._scan_end = datetime.now()

        duration = (self._scan_end - self._scan_start).total_seconds()
        logger.info(
            f"[SCANNER] Scan complete: {len(unique_printers)} printer(s) "
            f"found in {duration:.1f}s"
        )

        self._emit("scan_complete", {
            "printers_found": len(unique_printers),
            "duration_seconds": round(duration, 1),
        })

        return unique_printers

    def get_scan_summary(self) -> dict:
        """Summary of the last scan for GUI display and export."""
        duration = None
        if self._scan_start and self._scan_end:
            duration = (self._scan_end - self._scan_start).total_seconds()

        return {
            "scan_id": self.scan_id,
            "scan_start": self._scan_start.isoformat() if self._scan_start else None,
            "scan_end": self._scan_end.isoformat() if self._scan_end else None,
            "duration_seconds": duration,
            "printers_found": len(self.discovered_printers),
            "printers": [
                {
                    "ip_address": p.ip_address,
                    "mac_address": p.mac_address,
                    "hostname": p.hostname,
                    "manufacturer": p.manufacturer,
                    "model": p.model,
                    "protocol": p.protocol,
                    "open_ports": p.open_ports,
                    "response_time_ms": p.response_time_ms,
                    "online_status": p.online_status,
                    "discovery_method": p.discovery_method,
                    "friendly_name": p.friendly_name,
                    "device_subtype": p.device_subtype,
                    "location_notes": p.location_notes,
                }
                for p in self.discovered_printers
            ],
        }

    # =============================================================
    # PHASE 3A.1: Port Scan Discovery
    # =============================================================

    def _port_scan_discovery(self, network_cidr: str) -> List[DiscoveredPrinter]:
        """
        Scan network for ESC/POS printers on port 9100.

        Uses nmap for speed and reliability. Falls back to a
        pure-socket scan if nmap is not installed — ensures
        the scanner works on fresh Windows installs.
        """
        if self._is_nmap_available():
            return self._nmap_scan(network_cidr)

        logger.warning(
            "[SCANNER] nmap not found — falling back to socket scan. "
            "Install nmap for faster, more reliable scanning."
        )
        self._emit("progress", {
            "message": "nmap not found — using socket scan (slower but works)",
            "style": "warning",
        })
        return self._socket_scan(network_cidr)

    def _nmap_scan(self, network_cidr: str) -> List[DiscoveredPrinter]:
        """
        Scan using nmap — the preferred method.

        Uses nmap's parallel scanning for speed.
        -p 9100,515,631  : Printer ports
        -T4               : Aggressive timing (fast)
        --open            : Only show open ports
        """
        import nmap

        discovered = []
        nm = nmap.PortScanner()
        port_list = ",".join(str(p) for p in self.PRINTER_PORTS.keys())

        try:
            self._emit("progress", {
                "message": f"Scanning {network_cidr} for printer ports ({port_list})...",
                "style": "normal",
            })

            logger.info(f"[SCANNER] nmap scan: {network_cidr} ports {port_list}")
            nm.scan(hosts=network_cidr, arguments=f"-p {port_list} -T4 --open")

            total_hosts = len(nm.all_hosts())
            logger.info(f"[SCANNER] nmap found {total_hosts} responsive host(s)")

            for idx, host in enumerate(nm.all_hosts()):
                if nm[host].state() != "up":
                    continue

                # Collect open printer ports
                open_ports = []
                if "tcp" in nm[host]:
                    for port, port_info in nm[host]["tcp"].items():
                        if port_info["state"] == "open" and port in self.PRINTER_PORTS:
                            open_ports.append(port)

                if not open_ports:
                    continue

                # Determine protocol from highest-priority open port
                protocol = "escpos"
                if 9100 in open_ports:
                    protocol = "escpos"
                elif 631 in open_ports:
                    protocol = "ipp"
                elif 515 in open_ports:
                    protocol = "lpd"

                # Enrich with MAC, ping, hostname, manufacturer
                mac = self._get_mac_address(host)
                response_time = self._ping_host(host)
                hostname = self._reverse_dns(host)
                manufacturer = self._lookup_mac_manufacturer(mac) if mac != "unknown" else None

                printer = DiscoveredPrinter(
                    ip_address=host,
                    mac_address=mac,
                    hostname=hostname,
                    open_ports=sorted(open_ports),
                    response_time_ms=response_time,
                    manufacturer=manufacturer,
                    protocol=protocol,
                    online_status=True,
                    discovery_method="port_scan",
                    discovered_at=datetime.now(),
                    scan_id=self.scan_id,
                )

                discovered.append(printer)

                logger.info(
                    f"[SCANNER] Found: {host} "
                    f"(MAC: {mac}, ports: {open_ports}, {response_time:.1f}ms)"
                )

                self._emit("host_found", {
                    "ip": host,
                    "mac": mac,
                    "ports": open_ports,
                    "response_ms": round(response_time, 1),
                    "hostname": hostname,
                    "manufacturer": manufacturer,
                    "index": idx + 1,
                    "total": total_hosts,
                })

        except nmap.PortScannerError as e:
            error_msg = str(e)
            logger.error(f"[SCANNER] nmap error: {error_msg}")
            self._emit("error", {
                "message": f"nmap error: {error_msg}",
                "hint": "Make sure nmap is installed and you have sufficient permissions.",
            })

        except Exception as e:
            logger.error(f"[SCANNER] Unexpected scan error: {e}")
            self._emit("error", {"message": f"Scan error: {str(e)}"})

        logger.info(f"[SCANNER] nmap scan complete: {len(discovered)} printer(s) found")
        return discovered

    def _socket_scan(self, network_cidr: str) -> List[DiscoveredPrinter]:
        """
        Fallback scanner using pure Python sockets.

        Slower than nmap but has zero external dependencies.
        Scans printer ports on each host in the subnet.
        """
        discovered = []
        hosts = self._cidr_to_host_list(network_cidr)

        self._emit("progress", {
            "message": f"Socket scanning {len(hosts)} hosts for printer ports...",
            "style": "normal",
        })

        for idx, host in enumerate(hosts):
            if idx % 25 == 0:
                self._emit("progress", {
                    "message": f"Scanning... ({idx}/{len(hosts)} hosts checked)",
                    "style": "normal",
                })

            # Check all printer ports
            open_ports = []
            for port in self.PRINTER_PORTS.keys():
                if self._check_port(host, port, timeout=0.5):
                    open_ports.append(port)

            if not open_ports:
                continue

            # Found something — enrich it
            protocol = "escpos" if 9100 in open_ports else "ipp" if 631 in open_ports else "lpd"
            mac = self._get_mac_address(host)
            response_time = self._ping_host(host)
            hostname = self._reverse_dns(host)
            manufacturer = self._lookup_mac_manufacturer(mac) if mac != "unknown" else None

            printer = DiscoveredPrinter(
                ip_address=host,
                mac_address=mac,
                hostname=hostname,
                open_ports=sorted(open_ports),
                response_time_ms=response_time,
                manufacturer=manufacturer,
                protocol=protocol,
                online_status=True,
                discovery_method="port_scan",
                discovered_at=datetime.now(),
                scan_id=self.scan_id,
            )

            discovered.append(printer)

            logger.info(
                f"[SCANNER] Found: {host} "
                f"(MAC: {mac}, ports: {open_ports}, {response_time:.1f}ms)"
            )

            self._emit("host_found", {
                "ip": host,
                "mac": mac,
                "ports": open_ports,
                "response_ms": round(response_time, 1),
                "hostname": hostname,
                "manufacturer": manufacturer,
                "index": idx + 1,
                "total": len(hosts),
            })

        logger.info(f"[SCANNER] Socket scan complete: {len(discovered)} printer(s) found")
        return discovered

    # =============================================================
    # NETWORK HELPERS
    # =============================================================

    def _get_mac_address(self, ip: str) -> str:
        """
        Query ARP table for MAC address of a given IP.
        Cross-platform: handles Windows and Linux/macOS.
        """
        try:
            # Ping once to ensure ARP entry exists
            if IS_WINDOWS:
                subprocess.run(
                    ["ping", "-n", "1", "-w", "1000", ip],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            else:
                subprocess.run(
                    ["ping", "-c", "1", "-W", "1", ip],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )

            # Query ARP table
            if IS_WINDOWS:
                arp_result = subprocess.run(
                    ["arp", "-a", ip],
                    capture_output=True, text=True, timeout=5,
                )
            else:
                arp_result = subprocess.run(
                    ["arp", "-n", ip],
                    capture_output=True, text=True, timeout=5,
                )

            # Parse MAC — matches AA:BB:CC:DD:EE:FF or AA-BB-CC-DD-EE-FF
            mac_pattern = r"([0-9a-fA-F]{1,2}[:\-]){5}[0-9a-fA-F]{1,2}"
            match = re.search(mac_pattern, arp_result.stdout)

            if match:
                mac = match.group(0).upper().replace("-", ":")
                octets = mac.split(":")
                mac = ":".join(o.zfill(2) for o in octets)
                return mac

        except subprocess.TimeoutExpired:
            logger.debug(f"[SCANNER] ARP timeout for {ip}")
        except FileNotFoundError:
            logger.debug("[SCANNER] ARP command not found")
        except Exception as e:
            logger.debug(f"[SCANNER] MAC lookup failed for {ip}: {e}")

        return "unknown"

    def _ping_host(self, ip: str) -> float:
        """
        Measure ICMP ping response time in milliseconds.
        Cross-platform: handles Windows and Linux/macOS.
        """
        try:
            if IS_WINDOWS:
                ping_result = subprocess.run(
                    ["ping", "-n", "1", "-w", "2000", ip],
                    capture_output=True, text=True, timeout=5,
                )
                match = re.search(r"time[=<](\d+\.?\d*)\s*ms", ping_result.stdout)
            else:
                ping_result = subprocess.run(
                    ["ping", "-c", "1", "-W", "2", ip],
                    capture_output=True, text=True, timeout=5,
                )
                match = re.search(r"time=(\d+\.?\d*)\s*ms", ping_result.stdout)

            if match:
                return float(match.group(1))

        except subprocess.TimeoutExpired:
            logger.debug(f"[SCANNER] Ping timeout for {ip}")
        except FileNotFoundError:
            logger.debug("[SCANNER] Ping command not found")
        except Exception as e:
            logger.debug(f"[SCANNER] Ping failed for {ip}: {e}")

        return 0.0

    def _reverse_dns(self, ip: str) -> Optional[str]:
        """Attempt reverse DNS lookup for hostname."""
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except (socket.herror, socket.gaierror, OSError):
            return None

    def _check_port(self, ip: str, port: int, timeout: float = 0.5) -> bool:
        """Check if a specific TCP port is open on a host."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except (socket.error, OSError):
            return False

    def _lookup_mac_manufacturer(self, mac: str) -> Optional[str]:
        """
        Look up manufacturer from MAC address OUI prefix.

        The first 3 octets identify the manufacturer.
        Curated table for common POS printer brands.
        """
        if not mac or mac == "unknown":
            return None

        oui = mac.upper().replace("-", ":").split(":")[:3]
        if len(oui) < 3:
            return None
        oui_key = ":".join(oui)

        # Common POS printer manufacturer OUIs
        OUI_TABLE = {
            # Epson (Seiko Epson Corporation)
            "00:26:AB": "Epson",
            "AC:18:26": "Epson",
            "64:EB:8C": "Epson",
            "00:EB:D5": "Epson",
            # Star Micronics
            "00:11:62": "Star Micronics",
            "00:1A:B6": "Star Micronics",
            # Bixolon
            "1C:87:76": "Bixolon",
            "74:F0:7D": "Bixolon",
            # Citizen Systems
            "00:0B:CE": "Citizen",
            # Custom SPA (Italian POS printers)
            "00:07:80": "Custom",
            # Zebra Technologies
            "00:07:4D": "Zebra",
            "00:23:68": "Zebra",
            # HP
            "00:1A:4B": "HP",
            "3C:D9:2B": "HP",
            # Brother
            "00:80:77": "Brother",
            # Volcora — Alex's test printer
            "00:53:53": "Volcora",
        }

        return OUI_TABLE.get(oui_key)

    # =============================================================
    # UTILITY HELPERS
    # =============================================================

    def _is_nmap_available(self) -> bool:
        """Check if nmap is installed and accessible."""
        try:
            import nmap
            nm = nmap.PortScanner()
            nm.nmap_version()
            return True
        except ImportError:
            logger.debug("[SCANNER] python-nmap not installed")
            return False
        except Exception:
            logger.debug("[SCANNER] nmap binary not found")
            return False

    def _cidr_to_host_list(self, cidr: str) -> List[str]:
        """Convert CIDR notation to list of host IPs."""
        try:
            import ipaddress
            network = ipaddress.ip_network(cidr, strict=False)
            return [str(host) for host in network.hosts()]
        except (ValueError, ImportError) as e:
            logger.error(f"[SCANNER] Invalid CIDR: {cidr} — {e}")
            self._emit("error", {"message": f"Invalid network: {cidr}"})
            return []

    def _emit(self, event_type: str, data: dict) -> None:
        """
        Emit a progress event for the Overseer GUI.
        If no callback is registered, events are silently dropped.
        """
        if self.on_progress:
            try:
                self.on_progress(event_type, data)
            except Exception as e:
                logger.debug(f"[SCANNER] Progress callback error: {e}")

    def _generate_scan_id(self) -> str:
        """Generate a unique scan session ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique = str(uuid.uuid4())[:8]
        return f"scan_{timestamp}_{unique}"

    # ---------------------------------------------------------
    # Future Phase Stubs
    # ---------------------------------------------------------

    def _mdns_discovery(self) -> List[DiscoveredPrinter]:
        """Phase 3A.3: mDNS/Bonjour listener (future)."""
        raise NotImplementedError("Phase 3A.3: mDNS discovery not yet implemented")

    def _snmp_discovery(self, network_cidr: str) -> List[DiscoveredPrinter]:
        """Phase 3A.4: SNMP metadata queries (future)."""
        raise NotImplementedError("Phase 3A.4: SNMP discovery not yet implemented")

    def _usb_discovery(self) -> List[DiscoveredPrinter]:
        """Phase 3A.5: USB device enumeration (future)."""
        raise NotImplementedError("Phase 3A.5: USB discovery not yet implemented")

    # ---------------------------------------------------------
    # Deduplication
    # ---------------------------------------------------------

    def _deduplicate(self, printers: List[DiscoveredPrinter]) -> List[DiscoveredPrinter]:
        """Remove duplicate discoveries by IP address."""
        seen: dict[str, DiscoveredPrinter] = {}
        for printer in printers:
            existing = seen.get(printer.ip_address)
            if existing is None:
                seen[printer.ip_address] = printer
            else:
                if printer.manufacturer and not existing.manufacturer:
                    seen[printer.ip_address] = printer
        return list(seen.values())