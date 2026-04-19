"""
System Testing API Endpoint
Executes pytest test suite and streams output in real-time via Server-Sent Events.

File: backend/app/api/routes/system.py
Project: KINDpos - System Testing for Overseer

Nice. Dependable. Yours.
Every system tested. Every scenario validated.
"""

import os
import sys
import json
import re
import asyncio
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import settings

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/version")
async def get_version():
    """Return the current KINDpos version for Overseer header badge."""
    return {"version": settings.app_version}

# Project root: walk up from system.py until we find a directory containing 'backend' or 'app'
# Works both locally (deep nesting) and in Docker (/app/app/api/routes/system.py)
def _find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "pytest.ini").exists() or (parent / "fly.preview.toml").exists():
            return parent
        if (parent / "backend").is_dir() and (parent / "frontend").is_dir():
            return parent
    # Fallback: 5 levels up (original layout)
    try:
        return p.parents[5]
    except IndexError:
        return p.parents[len(p.parents) - 1]

PROJECT_ROOT = _find_project_root()


def classify_line(line: str) -> str:
    """
    Classify a pytest output line to determine frontend STYLING.
    This controls color only — not test counting.
    """
    if 'PASSED' in line or '\u2713' in line or '[PASS]' in line:
        return 'passed'
    elif 'FAILED' in line or 'ERROR' in line:
        return 'failed'
    elif 'SKIPPED' in line or 'SKIP' in line:
        return 'skipped'
    elif line.startswith('===') or line.startswith('---'):
        return 'header'
    elif re.search(r'\d+ passed', line):
        return 'summary'
    elif line.startswith('platform') or line.startswith('rootdir') or line.startswith('collected'):
        return 'meta'
    else:
        return 'normal'


def is_test_result(line: str) -> bool:
    """
    Determine if a line is an actual pytest test result (not narrative output).
    Real results have percentage brackets like [ 57%] or [100%].
    This is what we count — not every green line.
    """
    return bool(re.search(r'\[\s*\d+%\]', line))


def _run_pytest_in_thread(queue, loop):
    """
    Run pytest in a background thread using subprocess.Popen.
    Reads stdout line-by-line and pushes each line into an asyncio.Queue.
    """
    test_path = str(PROJECT_ROOT / 'core' / 'backend' / 'tests')

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'

    try:
        process = subprocess.Popen(
            [sys.executable, '-m', 'pytest', test_path, '-v', '-s', '--tb=short', '--color=no'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
            encoding='utf-8',
            errors='replace',
            bufsize=1
        )

        for line in process.stdout:
            line = line.rstrip()
            if line:
                asyncio.run_coroutine_threadsafe(queue.put(line), loop)

        process.wait()
        exit_code = process.returncode

    except Exception as e:
        asyncio.run_coroutine_threadsafe(
            queue.put(f"__ERROR__:{type(e).__name__}: {str(e)}"), loop
        )
        exit_code = 1

    asyncio.run_coroutine_threadsafe(queue.put(f"__DONE__:{exit_code}"), loop)


@router.post("/run-tests")
async def run_tests():
    """
    Execute the full pytest suite and stream output via Server-Sent Events.

    Full endpoint path: POST /api/v1/system/run-tests

    SSE Event Types:
        - start:    { type: 'start', timestamp: ISO8601 }
        - output:   { type: 'output', line: str, style: str, is_result: bool }
        - complete: { type: 'complete', exit_code: int, passed: int, failed: int, skipped: int }
    """

    async def test_stream():
        passed = 0
        failed = 0
        skipped = 0

        yield f"data: {json.dumps({'type': 'start', 'timestamp': datetime.now().isoformat()})}\n\n"

        queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        thread = threading.Thread(
            target=_run_pytest_in_thread,
            args=(queue, loop),
            daemon=True
        )
        thread.start()

        exit_code = 1
        while True:
            line = await queue.get()

            if line.startswith("__DONE__:"):
                exit_code = int(line.split(":")[1])
                break

            if line.startswith("__ERROR__:"):
                error_msg = line[len("__ERROR__:"):]
                yield f"data: {json.dumps({'type': 'output', 'line': error_msg, 'style': 'failed', 'is_result': False})}\n\n"
                continue

            style = classify_line(line)

            # Only count actual pytest result lines (with [ XX%] brackets)
            result_line = is_test_result(line)
            if result_line:
                if 'PASSED' in line:
                    passed += 1
                elif 'FAILED' in line:
                    failed += 1
                elif 'SKIPPED' in line:
                    skipped += 1

            event_data = {
                'type': 'output',
                'line': line,
                'style': style,
                'is_result': result_line
            }
            yield f"data: {json.dumps(event_data)}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'exit_code': exit_code, 'passed': passed, 'failed': failed, 'skipped': skipped})}\n\n"

    return StreamingResponse(
        test_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
