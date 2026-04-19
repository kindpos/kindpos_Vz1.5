import base64
import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.api.dependencies import get_ledger
from app.core.event_ledger import EventLedger
from app.core.events import EventType, Event, create_event, parse_event_type
from app.models.config_events import (
    StoreConfigBundle, StoreInfo, CCProcessingRate, PendingChange,
    Role, Employee, TipoutRule, MenuItem, MenuCategory, ModifierGroup,
    MandatoryAssignment, UniversalAssignment,
    Section, FloorPlanLayout, Terminal, Printer, RoutingMatrix
)
from app.config import settings
from app.services.store_config_service import StoreConfigService
from app.services.overseer_config_service import OverseerConfigService

# Allow-list of mime types we'll accept for the store logo. Keep this tight —
# rendering anything else risks XSS via SVG or unbounded payloads.
_ALLOWED_LOGO_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB

def _logo_storage_path() -> str:
    """Single fixed path for the store logo, sibling to the event ledger."""
    data_dir = os.path.dirname(os.path.abspath(settings.database_path))
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "store_logo.bin")


class LogoUploadRequest(BaseModel):
    filename: Optional[str] = None
    mime_type: str
    content_base64: str

router = APIRouter(prefix="/config", tags=["config"])

# Mock WebSocket broadcast for now as we don't have a real implementation handy in routers
async def broadcast_config_update(sections: List[str]):
    print(f"WS BROADCAST: config.updated for {sections}")

@router.get("/pricing")
async def get_pricing(ledger: EventLedger = Depends(get_ledger)):
    """Return canonical pricing constants from ledger (or env defaults)."""
    tax_rate = settings.tax_rate
    cash_discount_rate = settings.cash_discount_rate

    # Check for user-configured tax rules
    tax_events = await ledger.get_events_by_type(EventType.STORE_TAX_RULE_CREATED, limit=100)
    tax_events += await ledger.get_events_by_type(EventType.STORE_TAX_RULE_UPDATED, limit=100)
    tax_events.sort(key=lambda x: x.sequence_number or 0)
    for e in tax_events:
        if e.payload.get("applies_to") == "all":
            tax_rate = e.payload.get("rate_percent", tax_rate) / 100

    # Check for user-configured cash discount
    cc_events = await ledger.get_events_by_type(EventType.STORE_CC_PROCESSING_RATE_UPDATED, limit=10)
    cc_events.sort(key=lambda x: x.sequence_number or 0)
    if cc_events:
        last = cc_events[-1].payload
        if "cash_discount_rate" in last:
            cash_discount_rate = last["cash_discount_rate"]

    return {
        "tax_rate": tax_rate,
        "cash_discount_rate": cash_discount_rate,
    }


@router.get("/store", response_model=StoreConfigBundle)
async def get_store_config(ledger: EventLedger = Depends(get_ledger)):
    service = StoreConfigService(ledger)
    return await service.get_projected_config()

# New Overseer Endpoints
@router.get("/roles", response_model=List[Role])
async def get_roles(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_roles()

@router.get("/employees", response_model=List[Employee])
async def get_employees(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_employees()

@router.get("/tipout", response_model=List[TipoutRule])
async def get_tipout(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_tipout_rules()

@router.get("/menu/categories", response_model=List[MenuCategory])
async def get_menu_categories(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_menu_categories()

@router.get("/menu/items", response_model=List[MenuItem])
async def get_menu_items(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_menu_items()

@router.get("/modifier-groups", response_model=List[ModifierGroup])
async def get_modifier_groups(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_modifier_groups()

@router.get("/mandatory-assignments", response_model=List[MandatoryAssignment])
async def get_mandatory_assignments(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_mandatory_assignments()

@router.get("/universal-assignments", response_model=List[UniversalAssignment])
async def get_universal_assignments(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_universal_assignments()

@router.get("/floorplan/sections", response_model=List[Section])
async def get_floorplan_sections(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_floorplan_sections()

@router.get("/floorplan", response_model=FloorPlanLayout)
async def get_floorplan(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_floorplan_layout()

@router.get("/terminals", response_model=List[Terminal])
async def get_terminals(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_terminals()

@router.get("/routing", response_model=RoutingMatrix)
async def get_routing(ledger: EventLedger = Depends(get_ledger)):
    service = OverseerConfigService(ledger)
    return await service.get_routing_matrix()

@router.post("/store/logo")
async def upload_store_logo(
    req: LogoUploadRequest,
    background_tasks: BackgroundTasks,
    ledger: EventLedger = Depends(get_ledger),
):
    """Save an uploaded image as the store logo and emit a branding event.

    Body is JSON {mime_type, content_base64} — base64 keeps us free of
    python-multipart and works fine for the small images we expect here.
    """
    if req.mime_type not in _ALLOWED_LOGO_MIMES:
        raise HTTPException(status_code=400, detail=f"Unsupported mime type: {req.mime_type}")
    try:
        raw = base64.b64decode(req.content_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64")
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="empty image")
    if len(raw) > _LOGO_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"image exceeds {_LOGO_MAX_BYTES} bytes")

    path = _logo_storage_path()
    with open(path, "wb") as fh:
        fh.write(raw)

    event = create_event(
        event_type=EventType.STORE_BRANDING_UPDATED,
        terminal_id="OVERSEER",
        payload={
            "logo_url": "/api/v1/config/store/logo",
            "logo_mime_type": req.mime_type,
        },
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["store"])
    # Echo a cache-buster the client can use to refresh the <img> src.
    return {"status": "ok", "event_id": event.sequence_number, "logo_url": f"/api/v1/config/store/logo?v={event.sequence_number}"}


@router.get("/store/logo")
async def get_store_logo(ledger: EventLedger = Depends(get_ledger)):
    """Stream the most recently uploaded store logo, if any."""
    events = await ledger.get_events_by_type(EventType.STORE_BRANDING_UPDATED, limit=200)
    events.sort(key=lambda e: e.sequence_number or 0)
    mime_type = None
    for e in events:
        payload = e.payload or {}
        if payload.get("logo_mime_type"):
            mime_type = payload["logo_mime_type"]
    if not mime_type:
        raise HTTPException(status_code=404, detail="no logo uploaded")

    path = _logo_storage_path()
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="logo file missing")
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type=mime_type)


@router.post("/store/info")
async def update_store_info(info: StoreInfo, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    event = create_event(
        event_type=EventType.STORE_INFO_UPDATED,
        terminal_id="OVERSEER",
        payload=info.model_dump()
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["store"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.post("/store/cc-rate")
async def update_cc_rate(rate: CCProcessingRate, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    event = create_event(
        event_type=EventType.STORE_CC_PROCESSING_RATE_UPDATED,
        terminal_id="OVERSEER",
        payload=rate.model_dump()
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["store"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.post("/push")
async def push_changes(changes: List[PendingChange], background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    events = []
    sections = set()
    for change in changes:
        event = create_event(
            event_type=parse_event_type(change.event_type),
            terminal_id="OVERSEER",
            payload=change.payload
        )
        events.append(event)
        
        # Infer section from event type
        etype = change.event_type
        if etype.startswith("store."):
            sections.add("store")
        elif etype.startswith("employee.") or etype.startswith("tipout."):
            sections.add("employees")
        elif etype.startswith("menu.") or etype.startswith("category."):
            sections.add("menu")
        elif etype.startswith("modifier."):
            sections.add("modifiers")
        elif etype.startswith("floorplan."):
            sections.add("floor_plan")
        elif etype.startswith("terminal.") or etype.startswith("routing."):
            sections.add("hardware")
    
    if events:
        await ledger.append_batch(events)
        background_tasks.add_task(broadcast_config_update, list(sections))
    
    return {
        "status": "ok",
        "events_written": len(events),
        "event_ids": [e.sequence_number for e in events]
    }

@router.post("/menu/86")
async def item_86(item_id: str, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    event = create_event(
        event_type=EventType.MENU_ITEM_86D,
        terminal_id="OVERSEER",
        payload={"item_id": item_id}
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["menu"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.post("/menu/restore")
async def item_restore(item_id: str, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    event = create_event(
        event_type=EventType.MENU_ITEM_RESTORED,
        terminal_id="OVERSEER",
        payload={"item_id": item_id}
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["menu"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.post("/roles")
async def create_role(role: Role, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    event = create_event(
        event_type=EventType.EMPLOYEE_ROLE_CREATED,
        terminal_id="OVERSEER",
        payload=role.model_dump()
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["employees"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.put("/roles/{role_id}")
async def update_role(role_id: str, role: Role, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    event = create_event(
        event_type=EventType.EMPLOYEE_ROLE_UPDATED,
        terminal_id="OVERSEER",
        payload=role.model_dump()
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["employees"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    event = create_event(
        event_type=EventType.EMPLOYEE_ROLE_DELETED,
        terminal_id="OVERSEER",
        payload={"role_id": role_id}
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["employees"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.post("/employees")
async def create_employee(employee: Employee, background_tasks: BackgroundTasks, ledger: EventLedger = Depends(get_ledger)):
    # In a real system, we'd use employee.created event, 
    # but for now let's stick to the pattern.
    event = create_event(
        event_type=EventType.EMPLOYEE_CREATED,
        terminal_id="OVERSEER",
        payload=employee.model_dump()
    )
    await ledger.append(event)
    background_tasks.add_task(broadcast_config_update, ["employees"])
    return {"status": "ok", "event_id": event.sequence_number}

@router.get("/terminal-bundle")
async def get_terminal_bundle(ledger: EventLedger = Depends(get_ledger)):
    store_service = StoreConfigService(ledger)
    overseer_service = OverseerConfigService(ledger)
    
    return {
        "bundle_version": 1,
        "generated_at": "2026-03-24T14:30:00Z", # Should be dynamic
        "store": await store_service.get_projected_config(),
        "employees": await overseer_service.get_employees(),
        "roles": await overseer_service.get_roles(),
        "menu": {
            "categories": await overseer_service.get_menu_categories(),
            "items": await overseer_service.get_menu_items(),
            "modifier_groups": await overseer_service.get_modifier_groups(),
            "mandatory_assignments": await overseer_service.get_mandatory_assignments(),
            "universal_assignments": await overseer_service.get_universal_assignments()
        },
        "floor_plan": {
            "sections": await overseer_service.get_floorplan_sections(),
            "layout": await overseer_service.get_floorplan_layout()
        },
        "hardware": {
            "terminals": await overseer_service.get_terminals(),
            "printers": await overseer_service.get_printers(),
            "routing": await overseer_service.get_routing_matrix()
        }
    }
