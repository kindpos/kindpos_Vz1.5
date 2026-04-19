from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.api.dependencies import get_ledger
from app.core.event_ledger import EventLedger
from app.core.events import user_logged_in, user_logged_out, cash_tips_declared, EventType
from app.config import settings
from app.services.overseer_config_service import OverseerConfigService

router = APIRouter(prefix="/servers", tags=["staff"])


@router.get("")
async def get_servers(ledger: EventLedger = Depends(get_ledger)):
    """
    Returns active employees shaped for the terminal login roster.
    Called by the terminal UI on mount to populate the PIN login screen.
    """
    service = OverseerConfigService(ledger)
    employees = await service.get_employees()
    return {
        "servers": [
            {
                "id": e.employee_id,
                "name": e.display_name,
                "role": e.role_ids[0] if e.role_ids else "server",
                "roles": e.role_ids,
            }
            for e in employees
            if e.active
        ]
    }


# =============================================================================
# CLOCK IN / OUT
# =============================================================================

class ClockInRequest(BaseModel):
    employee_id: str
    employee_name: str
    pin: Optional[str] = None


class ClockOutRequest(BaseModel):
    employee_id: str
    employee_name: str


async def _clocked_in_ids(ledger: EventLedger) -> set:
    """Return the set of employee IDs currently clocked in."""
    login_events = await ledger.get_events_by_type(EventType.USER_LOGGED_IN)
    logout_events = await ledger.get_events_by_type(EventType.USER_LOGGED_OUT)
    all_events = sorted(login_events + logout_events, key=lambda x: x.sequence_number or 0)
    clocked_in: set = set()
    for e in all_events:
        eid = e.payload["employee_id"]
        if e.event_type == EventType.USER_LOGGED_IN:
            clocked_in.add(eid)
        else:
            clocked_in.discard(eid)
    return clocked_in


@router.post("/clock-in")
async def clock_in(request: ClockInRequest, ledger: EventLedger = Depends(get_ledger)):
    """Record a staff clock-in event."""
    if request.employee_id in await _clocked_in_ids(ledger):
        raise HTTPException(status_code=400, detail="Already clocked in")
    event = user_logged_in(
        terminal_id=settings.terminal_id,
        employee_id=request.employee_id,
        employee_name=request.employee_name,
    )
    await ledger.append(event)
    return {
        "success": True,
        "employee_id": request.employee_id,
        "employee_name": request.employee_name,
        "clocked_in_at": event.timestamp.isoformat(),
    }


@router.post("/clock-out")
async def clock_out(request: ClockOutRequest, ledger: EventLedger = Depends(get_ledger)):
    """Record a staff clock-out event."""
    if request.employee_id not in await _clocked_in_ids(ledger):
        raise HTTPException(status_code=400, detail="Not clocked in")
    event = user_logged_out(
        terminal_id=settings.terminal_id,
        employee_id=request.employee_id,
        employee_name=request.employee_name,
    )
    await ledger.append(event)
    return {
        "success": True,
        "employee_id": request.employee_id,
        "employee_name": request.employee_name,
        "clocked_out_at": event.timestamp.isoformat(),
    }


@router.get("/clocked-in")
async def get_clocked_in(ledger: EventLedger = Depends(get_ledger)):
    """Get all currently clocked-in staff by replaying login/logout events."""
    login_events = await ledger.get_events_by_type(EventType.USER_LOGGED_IN)
    logout_events = await ledger.get_events_by_type(EventType.USER_LOGGED_OUT)

    # Replay login/logout events in sequence order to determine current state
    clocked_in = {}
    all_events = sorted(login_events + logout_events, key=lambda x: x.sequence_number or 0)
    for e in all_events:
        eid = e.payload["employee_id"]
        if e.event_type == EventType.USER_LOGGED_IN:
            clocked_in[eid] = {
                "employee_id": eid,
                "employee_name": e.payload["employee_name"],
                "clocked_in_at": e.timestamp.isoformat(),
            }
        else:
            clocked_in.pop(eid, None)

    return {"staff": list(clocked_in.values())}


# =============================================================================
# CASH TIPS DECLARATION
# =============================================================================

class DeclareCashTipsRequest(BaseModel):
    server_id: str
    amount: float


@router.post("/declare-cash-tips")
async def declare_cash_tips(
    request: DeclareCashTipsRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Record a server's self-reported cash tips at checkout (optional)."""
    if request.amount < 0:
        raise HTTPException(status_code=400, detail="Tip amount cannot be negative")
    event = cash_tips_declared(
        terminal_id=settings.terminal_id,
        server_id=request.server_id,
        amount=request.amount,
        correlation_id=request.server_id,
    )
    await ledger.append(event)
    return {
        "success": True,
        "server_id": request.server_id,
        "amount": event.payload["amount"],
    }
