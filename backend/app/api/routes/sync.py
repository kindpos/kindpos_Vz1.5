"""LAN sync endpoints.

The Overseer is the authoritative source for configuration events. Terminals
pull config events from the Overseer via `GET /api/v1/sync/config/events`
and replay them into their local ledger, so every terminal ends up with the
same config projection as the Overseer.

Operational events (orders, shifts, payments) are *not* pulled by this route;
those flow from terminals up to the Overseer in a later phase.
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_ledger
from app.core.event_ledger import EventLedger
from app.core.events import (
    CONFIG_EVENT_PREFIXES,
    Event,
    EventType,
    create_event,
    is_config_event,
    parse_event_type,
)

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/health")
async def sync_health() -> dict[str, Any]:
    """Cheap heartbeat for terminals to confirm the Overseer is reachable."""
    return {"status": "ok", "role": "overseer"}


@router.get("/config/events")
async def get_config_events(
    since: int = 0,
    limit: int = 1000,
    ledger: EventLedger = Depends(get_ledger),
) -> dict[str, Any]:
    """Return config events with `sequence_number > since`, up to `limit`.

    Terminals call this on boot (and again periodically) with their
    last-seen sequence number to stay in sync with Overseer config.
    """
    if limit > 5000:
        limit = 5000

    # Over-fetch and filter: the ledger has config events interleaved with
    # operational events, so we ask for more than we need and filter down.
    events: list[Event] = []
    cursor = since
    while len(events) < limit:
        batch = await ledger.get_events_since(cursor, limit=limit * 2)
        if not batch:
            break
        for ev in batch:
            if is_config_event(ev.event_type.value):
                events.append(ev)
                if len(events) >= limit:
                    break
        cursor = batch[-1].sequence_number

    return {
        "events": [_event_to_dict(ev) for ev in events],
        "count": len(events),
        "latest_sequence": events[-1].sequence_number if events else since,
        "prefixes": list(CONFIG_EVENT_PREFIXES),
    }


@router.post("/config/events/replay")
async def replay_config_events(
    payload: dict[str, Any],
    ledger: EventLedger = Depends(get_ledger),
) -> dict[str, Any]:
    """Ingest a batch of config events from the Overseer into the local ledger.

    This is what a Terminal calls *on itself* after fetching events from the
    Overseer. Events are idempotent via event_id, so re-posting is safe.

    Body: {"events": [<event dict>, ...]}
    """
    raw_events = payload.get("events") or []
    if not isinstance(raw_events, list):
        raise HTTPException(400, "'events' must be a list")

    applied = 0
    skipped = 0
    for raw in raw_events:
        event_type_str = raw.get("event_type")
        if not event_type_str or not is_config_event(event_type_str):
            skipped += 1
            continue

        # Reuse the upstream event_id as the idempotency key so duplicate
        # replays are no-ops.
        idempotency_key = raw.get("event_id") or None

        try:
            event = create_event(
                event_type=parse_event_type(event_type_str),
                payload=raw.get("payload") or {},
                terminal_id=raw.get("terminal_id") or "OVERSEER",
                user_id=raw.get("user_id"),
                user_role=raw.get("user_role"),
                correlation_id=raw.get("correlation_id"),
                idempotency_key=idempotency_key,
            )
            # `ledger.append` returns the stored Event on success, or
            # `None` when the idempotency gate blocks a duplicate.
            # Previously this branch counted blocked duplicates as
            # applied because the return value was ignored — sync
            # replays reported false success on re-posts.
            stored = await ledger.append(event)
            if stored is None:
                skipped += 1
            else:
                applied += 1
        except ValueError as e:
            # Precision gate (non-2dp monetary value) raises ValueError.
            # Anything else bubbles up so real errors aren't swallowed.
            if "precision" in str(e).lower():
                skipped += 1
            else:
                raise

    return {"applied": applied, "skipped": skipped}


def _event_to_dict(ev: Event) -> dict[str, Any]:
    """Serialize an Event for the sync wire format."""
    return {
        "event_id": ev.event_id,
        "sequence_number": ev.sequence_number,
        "timestamp": ev.timestamp.isoformat(),
        "terminal_id": ev.terminal_id,
        "event_type": ev.event_type.value,
        "payload": ev.payload,
        "user_id": ev.user_id,
        "user_role": ev.user_role,
        "correlation_id": ev.correlation_id,
    }
