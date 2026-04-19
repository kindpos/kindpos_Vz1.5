"""KINDnostic runner — discovers and executes probes, records results."""

import importlib
import json
import os
import pkgutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Callable, Optional

import kindnostic.probes
from kindnostic.alerts import AlertQueue
from kindnostic.display import BootDisplay
from kindnostic.entomology import write_boot_diagnostic
from kindnostic.storage import BootStorage
from kindnostic.support_codes import generate_support_code
from kindnostic.types import Category, ProbeResult, Status

PROBE_TIMEOUT_S = 2.0
DEFAULT_DB_PATH = "./data/diagnostic_boot.db"

# ─── ANSI colors ─────────────────────────────────────────────
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_STATUS_COLOR = {
    Status.PASS: _GREEN,
    Status.WARN: _YELLOW,
    Status.FAIL: _RED,
}


def _use_color() -> bool:
    """Return True if stdout supports color."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# ─── Discovery ───────────────────────────────────────────────

def discover_probes() -> list[tuple[str, Callable, Category]]:
    """Scan kindnostic.probes for probe_* functions.

    Returns list of (name, callable, category) sorted by category
    (CRITICAL first, then HIGH, then LOW).
    """
    probes: list[tuple[str, Callable, Category]] = []

    package_path = kindnostic.probes.__path__
    for importer, module_name, is_pkg in pkgutil.iter_modules(package_path):
        module = importlib.import_module(f"kindnostic.probes.{module_name}")
        category = getattr(module, "CATEGORY", Category.LOW)

        for attr_name in dir(module):
            if attr_name.startswith("probe_") and callable(getattr(module, attr_name)):
                fn = getattr(module, attr_name)
                probes.append((attr_name, fn, category))

    probes.sort(key=lambda p: p[2])
    return probes


# ─── Single probe execution ─────────────────────────────────

def run_probe(
    fn: Callable, category: Category, timeout: float = PROBE_TIMEOUT_S
) -> tuple[ProbeResult, int]:
    """Execute a single probe with timeout enforcement.

    Returns (result, duration_ms).
    CRITICAL timeout -> FAIL, HIGH/LOW timeout -> WARN.
    Any unhandled exception -> FAIL.
    """
    probe_name = fn.__name__.removeprefix("probe_")
    start = time.monotonic()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn)
            result = future.result(timeout=timeout)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return result, elapsed_ms

    except TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        timeout_status = Status.FAIL if category == Category.CRITICAL else Status.WARN
        return ProbeResult(
            probe_name=probe_name,
            category=category,
            status=timeout_status,
            message=f"Probe timed out after {timeout}s",
            metadata={"timeout_seconds": timeout},
        ), elapsed_ms

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ProbeResult(
            probe_name=probe_name,
            category=category,
            status=Status.FAIL,
            message=f"Probe raised exception: {exc}",
            metadata={"exception": type(exc).__name__, "detail": str(exc)},
        ), elapsed_ms


# ─── Output formatting ──────────────────────────────────────

def _format_result_line(result: ProbeResult, duration_ms: int, color: bool) -> str:
    """Format a single probe result as a terminal line."""
    status = result.status.value
    name = result.probe_name
    cat = result.category.value
    ms = f"{duration_ms}ms"

    if color:
        c = _STATUS_COLOR.get(result.status, "")
        line = f"  {c}{status:4s}{_RESET}  {cat:8s}  {name:<35s} {_DIM}{ms:>6s}{_RESET}"
    else:
        line = f"  {status:4s}  {cat:8s}  {name:<35s} {ms:>6s}"

    if result.message:
        if color:
            line += f"  {_DIM}{result.message}{_RESET}"
        else:
            line += f"  {result.message}"

    return line


def _format_verbose(result: ProbeResult, duration_ms: int, color: bool) -> str:
    """Format a probe result with metadata detail."""
    line = _format_result_line(result, duration_ms, color)
    if result.metadata:
        meta_str = json.dumps(result.metadata, indent=2, default=str)
        indent = "          "
        for meta_line in meta_str.split("\n"):
            line += f"\n{indent}{meta_line}"
    return line


def _format_summary(
    results: list[tuple[ProbeResult, int]], total_ms: int, outcome: str, color: bool
) -> str:
    """Format the summary footer."""
    passed = sum(1 for r, _ in results if r.status == Status.PASS)
    warned = sum(1 for r, _ in results if r.status == Status.WARN)
    failed = sum(1 for r, _ in results if r.status == Status.FAIL)

    if color:
        parts = [
            f"{_GREEN}{passed} passed{_RESET}",
            f"{_YELLOW}{warned} warned{_RESET}" if warned else None,
            f"{_RED}{failed} failed{_RESET}" if failed else None,
        ]
        parts_str = ", ".join(p for p in parts if p)
        outcome_color = _GREEN if outcome == "READY" else _RED
        return (
            f"\n  {_BOLD}KINDnostic{_RESET}: {parts_str} "
            f"in {total_ms}ms — {outcome_color}{_BOLD}{outcome}{_RESET}"
        )
    else:
        parts = [f"{passed} passed"]
        if warned:
            parts.append(f"{warned} warned")
        if failed:
            parts.append(f"{failed} failed")
        return f"\n  KINDnostic: {', '.join(parts)} in {total_ms}ms — {outcome}"


def _format_json(
    results: list[tuple[ProbeResult, int]], boot_id: str, total_ms: int, outcome: str
) -> str:
    """Format all results as a JSON document."""
    data = {
        "boot_id": boot_id,
        "outcome": outcome,
        "duration_ms": total_ms,
        "probes": [
            {
                "probe_name": r.probe_name,
                "category": r.category.value,
                "status": r.status.value,
                "duration_ms": ms,
                "message": r.message,
                "metadata": r.metadata,
            }
            for r, ms in results
        ],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r, _ in results if r.status == Status.PASS),
            "warned": sum(1 for r, _ in results if r.status == Status.WARN),
            "failed": sum(1 for r, _ in results if r.status == Status.FAIL),
        },
    }
    return json.dumps(data, indent=2, default=str)


def _print_results(
    results: list[tuple[ProbeResult, int]],
    boot_id: str,
    total_ms: int,
    outcome: str,
    verbose: bool = False,
    json_output: bool = False,
) -> None:
    """Print results to stdout."""
    if json_output:
        print(_format_json(results, boot_id, total_ms, outcome))
        return

    color = _use_color()

    for result, ms in results:
        if verbose:
            print(_format_verbose(result, ms, color))
        else:
            print(_format_result_line(result, ms, color))

    print(_format_summary(results, total_ms, outcome, color))


# ─── Main entry points ──────────────────────────────────────

def run_all(
    db_path: Optional[str] = None,
    verbose: bool = False,
    json_output: bool = False,
    display: bool = False,
) -> int:
    """Main entry point. Discover probes, execute, store results, return exit code.

    Returns 0 if no CRITICAL probes failed, 1 if any did.
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    boot_id = str(uuid.uuid4())
    start = time.monotonic()

    # Start boot display server if requested
    boot_display: Optional[BootDisplay] = None
    if display:
        boot_display = BootDisplay()
        boot_display.start()
        boot_display.state.boot_id = boot_id

    probes = discover_probes()

    results: list[tuple[ProbeResult, int]] = []
    for i, (name, fn, category) in enumerate(probes):
        if boot_display:
            boot_display.state.set_progress(i, len(probes), name.removeprefix("probe_"))
        result, duration_ms = run_probe(fn, category)
        results.append((result, duration_ms))

    if boot_display:
        boot_display.state.set_progress(len(probes), len(probes), "complete")

    total_ms = int((time.monotonic() - start) * 1000)

    # Determine outcome
    has_critical_fail = any(
        r.status == Status.FAIL and r.category == Category.CRITICAL
        for r, _ in results
    )
    outcome = "BLOCKED" if has_critical_fail else "READY"
    exit_code = 1 if has_critical_fail else 0

    # Update boot display with final screen
    if boot_display:
        boot_display.state.outcome = outcome
        warnings = [
            {"probe": r.probe_name, "message": r.message or ""}
            for r, _ in results if r.status == Status.WARN
        ]
        if has_critical_fail:
            failed = [
                {"probe": r.probe_name, "message": r.message or "unknown"}
                for r, _ in results
                if r.status == Status.FAIL and r.category == Category.CRITICAL
            ]
            code = generate_support_code(failed[0]["probe"]) if failed else "KN-XX-0000"
            boot_display.state.set_failure(failed, code)

            # Wait for manager override (blocking — this keeps the service running)
            import time as _time
            while not boot_display.state.override_completed:
                _time.sleep(0.5)

            # Override was completed — update outcome
            outcome = "OVERRIDE"
            exit_code = 0
        else:
            boot_display.state.set_success(warnings if warnings else None)

    # Print results
    _print_results(results, boot_id, total_ms, outcome, verbose, json_output)

    # Persist
    passed = sum(1 for r, _ in results if r.status == Status.PASS)
    warned = sum(1 for r, _ in results if r.status == Status.WARN)
    failed = sum(1 for r, _ in results if r.status == Status.FAIL)

    with BootStorage(db_path) as storage:
        for result, duration_ms in results:
            storage.record_result(
                boot_id=boot_id,
                probe_name=result.probe_name,
                category=result.category.value,
                status=result.status.value,
                duration_ms=duration_ms,
                message=result.message,
                metadata=result.metadata,
            )
        storage.record_summary(
            boot_id=boot_id,
            total_probes=len(results),
            passed=passed,
            warned=warned,
            failed=failed,
            duration_ms=total_ms,
            outcome=outcome,
        )

    # Write BOOT_DIAGNOSTIC event to Entomology
    try:
        write_boot_diagnostic(
            boot_id=boot_id,
            outcome=outcome,
            results=results,
            total_duration_ms=total_ms,
            db_path=db_path,
        )
    except Exception:
        pass  # Entomology integration is best-effort

    # Enqueue alert if any failures/warnings
    try:
        with AlertQueue(db_path) as alerts:
            alerts.enqueue(
                boot_id=boot_id,
                terminal_id=os.environ.get("KINDPOS_TERMINAL_ID", "terminal_01"),
                results=results,
            )
            alerts.flush()  # Attempt to send if webhook configured
    except Exception:
        pass  # Alert queue is best-effort

    # Stop boot display server
    if boot_display:
        # Give browser a moment to load the final screen
        time.sleep(1)
        boot_display.stop()

    return exit_code


def run_single_probe(
    probe_name: str,
    db_path: Optional[str] = None,
    verbose: bool = False,
    json_output: bool = False,
) -> int:
    """Run a single probe by name. For support debugging."""
    probes = discover_probes()

    # Match by probe function name or probe_name field
    target = None
    for name, fn, category in probes:
        short_name = name.removeprefix("probe_")
        if short_name == probe_name or name == probe_name:
            target = (name, fn, category)
            break

    if target is None:
        available = [n.removeprefix("probe_") for n, _, _ in probes]
        print(f"Unknown probe: {probe_name}", file=sys.stderr)
        print(f"Available: {', '.join(available)}", file=sys.stderr)
        return 2

    name, fn, category = target
    result, duration_ms = run_probe(fn, category)
    results = [(result, duration_ms)]

    outcome = "FAIL" if result.status == Status.FAIL else "PASS"
    _print_results(results, "single-run", duration_ms, outcome, verbose, json_output)

    # Persist if db_path given
    if db_path:
        with BootStorage(db_path) as storage:
            storage.record_result(
                boot_id="single-run",
                probe_name=result.probe_name,
                category=result.category.value,
                status=result.status.value,
                duration_ms=duration_ms,
                message=result.message,
                metadata=result.metadata,
            )

    return 1 if result.status == Status.FAIL else 0
