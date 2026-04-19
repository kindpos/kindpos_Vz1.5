"""KINDnostic boot display — HTML screens served via lightweight HTTP server.

Approach: Option B from spec — minimal HTTP server on port 8888 during boot.
The kiosk browser opens http://localhost:8888 and sees:
  - Progress screen during probe execution
  - Success screen (brief, then redirect to KINDpos)
  - Failure screen with support code + Manager Override form
"""

import json
import os
import sqlite3
import threading
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Optional
from urllib.parse import parse_qs

from kindnostic.entomology import write_boot_diagnostic
from kindnostic.support_codes import generate_support_code
from kindnostic.types import ProbeResult, Status

BOOT_DISPLAY_PORT = 8888
KINDPOS_URL = "http://localhost:8000"

# ─── HTML Templates ──────────────────────────────────────────

_BASE_STYLE = """
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
    background: #0a0a0a; color: #e0e0e0;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh; padding: 20px;
  }
  .container { max-width: 600px; width: 100%; text-align: center; }
  h1 { font-size: 24px; margin-bottom: 16px; }
  .status { font-size: 18px; margin: 12px 0; }
  .progress-bar {
    background: #222; border-radius: 8px; height: 24px;
    overflow: hidden; margin: 20px 0;
  }
  .progress-fill {
    background: linear-gradient(90deg, #00c853, #69f0ae);
    height: 100%; border-radius: 8px;
    transition: width 0.3s ease;
  }
  .probe-list { text-align: left; margin: 16px 0; font-size: 14px; }
  .probe-item { padding: 4px 0; font-family: monospace; }
  .probe-pass { color: #69f0ae; }
  .probe-warn { color: #ffd740; }
  .probe-fail { color: #ff5252; }
  .error-box {
    background: #1a0000; border: 2px solid #ff5252;
    border-radius: 12px; padding: 24px; margin: 20px 0;
  }
  .support-code {
    font-family: monospace; font-size: 28px; font-weight: bold;
    color: #ff5252; margin: 12px 0;
  }
  .btn {
    display: inline-block; padding: 14px 28px; margin: 8px;
    border-radius: 8px; font-size: 16px; font-weight: bold;
    cursor: pointer; border: none; text-decoration: none;
  }
  .btn-support { background: #1565c0; color: white; }
  .btn-override { background: #424242; color: white; }
  .btn-override:hover { background: #616161; }
  .pin-form { margin: 20px 0; }
  .pin-input {
    font-size: 24px; text-align: center; width: 200px;
    padding: 12px; background: #222; color: white;
    border: 2px solid #555; border-radius: 8px;
    -webkit-text-security: disc;
  }
  .pin-input:focus { border-color: #69f0ae; outline: none; }
  .pin-error { color: #ff5252; margin: 8px 0; font-size: 14px; }
  .warning-badge {
    display: inline-block; background: #ff8f00; color: #000;
    padding: 6px 16px; border-radius: 20px; font-size: 13px;
    font-weight: bold; cursor: pointer; margin: 8px 0;
  }
  .warning-details {
    text-align: left; background: #1a1400; border: 1px solid #ff8f00;
    border-radius: 8px; padding: 16px; margin: 8px 0;
    font-size: 13px; display: none;
  }
  .contact-info { font-size: 14px; color: #999; margin: 12px 0; }
</style>
"""


def render_progress(current: int, total: int, probe_name: str) -> str:
    """Render the boot progress screen."""
    pct = int((current / max(total, 1)) * 100)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>KINDnostic</title>
<meta http-equiv="refresh" content="1">
{_BASE_STYLE}
</head><body>
<div class="container">
  <h1>KINDnostic</h1>
  <div class="status">Verifying system integrity...</div>
  <div class="progress-bar">
    <div class="progress-fill" style="width: {pct}%"></div>
  </div>
  <div class="status" style="font-size: 14px; color: #999;">
    [{current}/{total}] {probe_name}
  </div>
</div>
</body></html>"""


def render_success(warnings: list[dict] | None = None) -> str:
    """Render the success screen. Redirects to KINDpos after 2 seconds."""
    warning_html = ""
    if warnings:
        items = "".join(
            f'<div class="probe-item probe-warn">{w["probe"]}: {w["message"]}</div>'
            for w in warnings
        )
        warning_html = f"""
        <div class="warning-badge" onclick="document.getElementById('warn-details').style.display='block'">
          {len(warnings)} warning(s) — tap for details
        </div>
        <div class="warning-details" id="warn-details">{items}</div>
        """

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>KINDnostic</title>
<meta http-equiv="refresh" content="3;url={KINDPOS_URL}">
{_BASE_STYLE}
</head><body>
<div class="container">
  <h1>KINDnostic &#10003;</h1>
  <div class="status">All systems verified</div>
  <div class="progress-bar">
    <div class="progress-fill" style="width: 100%"></div>
  </div>
  {warning_html}
</div>
</body></html>"""


def render_failure(
    failed_probes: list[dict],
    support_code: str,
    pin_error: str = "",
) -> str:
    """Render the CRITICAL failure screen with support code and override form."""
    failure_items = "".join(
        f'<div class="probe-item probe-fail">{p["probe"]}: {p["message"]}</div>'
        for p in failed_probes
    )

    pin_error_html = (
        f'<div class="pin-error">{pin_error}</div>' if pin_error else ""
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>KINDnostic — System Check Failed</title>
{_BASE_STYLE}
</head><body>
<div class="container">
  <h1>&#9888; KINDnostic — System Check Failed</h1>

  <div class="error-box">
    <div class="probe-list">{failure_items}</div>
    <div style="margin-top: 16px; font-size: 14px; color: #ccc;">
      This terminal cannot accept orders until the issue is resolved.
    </div>
    <div class="support-code">{support_code}</div>
  </div>

  <div style="display: flex; gap: 16px; justify-content: center; flex-wrap: wrap;">
    <div style="flex: 1; min-width: 250px;">
      <button class="btn btn-support"
              onclick="document.getElementById('contact').style.display='block'">
        Call Support
      </button>
      <div class="contact-info" id="contact" style="display: none;">
        KIND Technologies Support<br>
        Reference code: {support_code}
      </div>
    </div>

    <div style="flex: 1; min-width: 250px;">
      <button class="btn btn-override"
              onclick="document.getElementById('override-form').style.display='block'">
        Manager Override
      </button>
      <div class="pin-form" id="override-form" style="display: none;">
        <form method="POST" action="/override">
          <input type="password" name="pin" class="pin-input"
                 placeholder="Manager PIN" inputmode="numeric"
                 pattern="[0-9]*" autocomplete="off">
          {pin_error_html}
          <br><br>
          <button type="submit" class="btn btn-override">Confirm Override</button>
        </form>
      </div>
    </div>
  </div>
</div>
</body></html>"""


def render_warning_indicator(warnings: list[dict]) -> str:
    """Render the amber warning indicator for the login screen.

    Returns an HTML snippet (not a full page) to embed in the login screen.
    """
    if not warnings:
        return ""

    items = "".join(
        f'<div class="probe-item probe-warn">{w["probe"]}: {w["message"]}</div>'
        for w in warnings
    )

    return f"""
<div class="warning-badge" onclick="this.nextElementSibling.style.display=
  this.nextElementSibling.style.display==='none'?'block':'none'">
  {len(warnings)} boot warning(s)
</div>
<div class="warning-details">{items}</div>
"""


# ─── Manager Override Validation ─────────────────────────────

def validate_manager_pin(pin: str, ledger_db_path: Optional[str] = None) -> Optional[str]:
    """Validate a PIN against the event ledger's employee records.

    Returns the employee_id if valid manager, None otherwise.
    """
    if ledger_db_path is None:
        ledger_db_path = os.environ.get("KINDPOS_DB_PATH", "./data/event_ledger.db")

    if not os.path.exists(ledger_db_path):
        return None

    conn = sqlite3.connect(ledger_db_path)
    try:
        # Get latest EMPLOYEE_CREATED events to build current employee list
        rows = conn.execute(
            """SELECT payload FROM events
               WHERE event_type IN ('EMPLOYEE_CREATED', 'employee.created')
               ORDER BY sequence_number ASC"""
        ).fetchall()

        employees: dict[str, dict] = {}
        for (payload_json,) in rows:
            try:
                payload = json.loads(payload_json)
                emp_id = payload.get("employee_id")
                if emp_id:
                    employees[emp_id] = payload
            except (json.JSONDecodeError, TypeError):
                continue

        # Check for updates
        update_rows = conn.execute(
            """SELECT payload FROM events
               WHERE event_type IN ('EMPLOYEE_UPDATED', 'employee.updated')
               ORDER BY sequence_number ASC"""
        ).fetchall()
        for (payload_json,) in update_rows:
            try:
                payload = json.loads(payload_json)
                emp_id = payload.get("employee_id")
                if emp_id and emp_id in employees:
                    employees[emp_id].update(payload)
            except (json.JSONDecodeError, TypeError):
                continue

        # Find matching active manager
        for emp_id, emp in employees.items():
            if (emp.get("pin") == pin
                    and emp.get("role_id") in ("manager", "Manager")
                    and emp.get("active", True)):
                return emp_id

        return None
    finally:
        conn.close()


# ─── Boot Display Server ────────────────────────────────────

class BootDisplayState:
    """Shared state between the HTTP server and the runner."""

    def __init__(self) -> None:
        self.current_screen: str = render_progress(0, 1, "initializing...")
        self.boot_id: str = ""
        self.outcome: str = ""
        self.failed_probes: list[dict] = []
        self.warnings: list[dict] = []
        self.support_code: str = ""
        self.override_completed: bool = False
        self.override_employee: Optional[str] = None
        self.pin_error: str = ""
        self._lock = threading.Lock()

    def set_progress(self, current: int, total: int, probe_name: str) -> None:
        with self._lock:
            self.current_screen = render_progress(current, total, probe_name)

    def set_success(self, warnings: list[dict] | None = None) -> None:
        with self._lock:
            self.warnings = warnings or []
            self.current_screen = render_success(warnings)

    def set_failure(self, failed_probes: list[dict], support_code: str) -> None:
        with self._lock:
            self.failed_probes = failed_probes
            self.support_code = support_code
            self.pin_error = ""
            self.current_screen = render_failure(failed_probes, support_code)

    def handle_override(self, pin: str) -> bool:
        """Validate PIN and update state. Returns True if override successful."""
        employee_id = validate_manager_pin(pin)
        with self._lock:
            if employee_id:
                self.override_completed = True
                self.override_employee = employee_id
                self.current_screen = render_success()
                return True
            else:
                self.pin_error = "Invalid manager PIN"
                self.current_screen = render_failure(
                    self.failed_probes, self.support_code, self.pin_error
                )
                return False

    def get_warning_indicator(self) -> str:
        """Get the amber warning HTML snippet for the login screen."""
        with self._lock:
            return render_warning_indicator(self.warnings)


def _make_handler(state: BootDisplayState):
    """Create an HTTP request handler class bound to the given state."""

    class BootHandler(BaseHTTPRequestHandler):

        def do_GET(self) -> None:
            if self.path == "/warnings":
                content = state.get_warning_indicator()
            elif self.path == "/status":
                data = json.dumps({
                    "outcome": state.outcome,
                    "override": state.override_completed,
                })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data.encode())
                return
            else:
                with state._lock:
                    content = state.current_screen

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode())

        def do_POST(self) -> None:
            if self.path == "/override":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                params = parse_qs(body)
                pin = params.get("pin", [""])[0]

                success = state.handle_override(pin)

                if success:
                    # Log the override to Entomology
                    try:
                        write_boot_diagnostic(
                            boot_id=state.boot_id,
                            outcome="OVERRIDE",
                            results=[],
                            total_duration_ms=0,
                            db_path=os.environ.get(
                                "KINDPOS_DIAG_DB_PATH",
                                "./data/diagnostic_boot.db",
                            ),
                        )
                    except Exception:
                        pass

                # Redirect back to main page
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Suppress HTTP logs during boot

    return BootHandler


class BootDisplay:
    """Manages the boot display HTTP server lifecycle."""

    def __init__(self, port: int = BOOT_DISPLAY_PORT) -> None:
        self.port = port
        self.state = BootDisplayState()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the HTTP server in a background thread."""
        handler = _make_handler(self.state)
        try:
            self._server = HTTPServer(("0.0.0.0", self.port), handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
        except OSError:
            # Port already in use — skip display server
            self._server = None

    def stop(self) -> None:
        """Shut down the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None

    def __enter__(self) -> "BootDisplay":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
