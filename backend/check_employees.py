"""
Quick diagnostic — shows which DB files exist and what employees are in each.
Run from backend/ directory:
    ..\\.venv\\Scripts\\python.exe check_employees.py
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.core.event_ledger import EventLedger
from app.core.events import EventType

DB_CANDIDATES = [
    "./data/event_ledger.db",                                    # backend/ relative
    "../data/event_ledger.db",                                   # project root relative
]

async def check(path):
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        print(f"  [{path}]  NOT FOUND")
        return
    ledger = EventLedger(path)
    await ledger.connect()
    events = await ledger.get_events_by_type(EventType.EMPLOYEE_CREATED, limit=100)
    print(f"  [{p.resolve()}]  {len(events)} EMPLOYEE_CREATED event(s)")
    for e in events:
        print(f"    - {e.payload.get('display_name')}  PIN: {e.payload.get('pin')}  roles: {e.payload.get('role_ids', e.payload.get('role_id'))}")
    await ledger.close()

async def main():
    for db in DB_CANDIDATES:
        await check(db)

asyncio.run(main())
