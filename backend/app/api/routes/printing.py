import asyncio
import json
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pathlib import Path

import aiosqlite

from ..dependencies import get_ledger, get_print_dispatcher
from ...core.event_ledger import EventLedger
from ...printing.print_queue import PrintJobQueue
from ...services.print_context_builder import PrintContextBuilder
from .hardware import HARDWARE_DB_PATH, _ensure_db

router = APIRouter(prefix="/print", tags=["printing"])

# In a real app, these would be managed by dependency injection
# For this task, we initialize them here or in main.py
print_queue = PrintJobQueue()
# Note: In production, PrintContextBuilder would be injected with the ledger

_logger = logging.getLogger(__name__)

@router.post("/receipt/{order_id}")
async def print_receipt(
    order_id: str,
    copy_type: str = "customer",   # query param: customer | merchant | itemized
    ledger: EventLedger = Depends(get_ledger),
):
    """Trigger receipt print for completed order. copy_type defaults to customer."""
    builder = PrintContextBuilder(ledger)
    context = await builder.build_receipt_context(order_id, copy_type=copy_type)
    job_id  = await print_queue.enqueue(
        order_id=order_id,
        template_id="guest_receipt",
        printer_mac="DEFAULT_RECEIPT",
        ticket_number=context.get("ticket_number", "N/A"),
        context=context,
        copy_type=copy_type,
    )
    return {"status": "queued", "job_id": job_id, "copy_type": copy_type}

@router.post("/ticket/{order_id}")
async def print_ticket(
    order_id: str,
    void: bool = False,
    ledger: EventLedger = Depends(get_ledger),
):
    """Trigger kitchen ticket for order. Pass ?void=true for void tickets.

    Routing logic:
    - Load kitchen printers from hardware_config.db
    - Printers with assigned categories only receive items in those categories
    - Printers with NO categories receive all items (catch-all)
    - Each printer gets a separate ticket with companion_items showing
      what the other printers are making
    """
    await _ensure_db()
    builder = PrintContextBuilder(ledger)
    template = "kitchen_ticket_void" if void else "kitchen_ticket"

    # Load kitchen printers and their category assignments
    async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices WHERE type = 'kitchen' ORDER BY saved_at"
        ) as cur:
            printers = [dict(row) async for row in cur]

    # Parse category lists
    for p in printers:
        cats = p.get('categories', '')
        p['categories_list'] = [c.strip() for c in cats.split(',') if c.strip()] if cats else []

    # If no kitchen printers saved, fall back to DEFAULT_KITCHEN with all items
    if not printers:
        printers = [{'mac': 'DEFAULT_KITCHEN', 'name': 'Kitchen', 'categories_list': []}]

    # Build one ticket per printer, filtering by category
    job_ids = []
    ticket_total = len(printers)
    for idx, printer in enumerate(printers):
        cats = printer['categories_list']
        context = await builder.build_kitchen_context(
            order_id,
            station_name=printer.get('name', 'Kitchen'),
            station_categories=cats if cats else None,
        )
        context['ticket_index'] = idx + 1
        context['ticket_total'] = ticket_total
        if void:
            context["is_void"] = True
            context["void_banner"] = "** VOID **"

        # Skip printers that would get zero items for this order
        if not context.get('items'):
            continue

        job_id = await print_queue.enqueue(
            order_id=order_id,
            template_id=template,
            printer_mac=printer['mac'],
            ticket_number=context.get('ticket_number', 'N/A'),
            context=context,
        )
        job_ids.append(job_id)

    return {"status": "queued", "job_ids": job_ids, "printers": len(job_ids), "is_void": void}

@router.get("/queue")
async def get_queue():
    """Return all queued and failed print jobs."""
    pending = await print_queue.get_pending_jobs()
    failed = await print_queue.get_failed_jobs()
    return {"pending": pending, "failed": failed}

@router.post("/queue/{job_id}/retry")
async def retry_job(job_id: str):
    """Manually retry a failed job."""
    await print_queue.reset_for_retry(job_id)
    return {"status": "reset_for_retry", "job_id": job_id}

class ClockHoursRequest(BaseModel):
    employee_name: str
    role_name: str = ""
    action: str = "CLOCK IN"


@router.post("/clock-hours/{employee_id}")
async def print_clock_hours(
    employee_id: str,
    request: ClockHoursRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Print shift hours and pay-period summary on clock in/out."""
    builder = PrintContextBuilder(ledger)
    context = await builder.build_clock_hours_context(
        employee_id=employee_id,
        employee_name=request.employee_name,
        role_name=request.role_name,
        action=request.action,
    )
    job_id = await print_queue.enqueue(
        order_id=f"clock-{employee_id}",
        template_id="clock_hours",
        printer_mac="DEFAULT_RECEIPT",
        ticket_number="CLK",
        context=context,
    )
    return {"status": "queued", "job_id": job_id}


class SalesRecapRequest(BaseModel):
    printed_by: str = "Manager"


@router.post("/sales-recap")
async def print_sales_recap(
    request: SalesRecapRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Print end-of-day sales recap report."""
    builder = PrintContextBuilder(ledger)
    context = await builder.build_sales_recap_context(printed_by=request.printed_by)
    job_id = await print_queue.enqueue(
        order_id="sales-recap",
        template_id="sales_recap",
        printer_mac="DEFAULT_RECEIPT",
        ticket_number="RPT",
        context=context,
    )
    return {"status": "queued", "job_id": job_id}


class ServerCheckoutPrintRequest(BaseModel):
    server_name: str = ""
    declared_cash_tips: Optional[float] = None


@router.post("/server-checkout/{server_id}")
async def print_server_checkout(
    server_id: str,
    request: ServerCheckoutPrintRequest,
    ledger: EventLedger = Depends(get_ledger),
):
    """Print server checkout report."""
    builder = PrintContextBuilder(ledger)
    context = await builder.build_server_checkout_context(
        server_id=server_id,
        server_name=request.server_name,
        declared_cash_tips=request.declared_cash_tips,
    )
    job_id = await print_queue.enqueue(
        order_id=f"checkout-{server_id}",
        template_id="server_checkout",
        printer_mac="DEFAULT_RECEIPT",
        ticket_number="CHK",
        context=context,
    )
    return {"status": "queued", "job_id": job_id}


@router.post("/test")
async def print_test(template_name: str = Body(..., embed=True), printer_mac: str = Body(..., embed=True)):
    """Fire a fixture template to a printer (test panel)."""
    fixture_path = Path(__file__).resolve().parents[2] / "printing" / "fixtures" / f"{template_name}.json"
    if not fixture_path.exists():
        raise HTTPException(status_code=404, detail=f"Fixture {template_name} not found")
    
    with open(fixture_path, 'r') as f:
        context = json.load(f)
    
    job_id = await print_queue.enqueue(
        order_id=context.get('order_id', 'TEST'),
        template_id=template_name,
        printer_mac=printer_mac,
        ticket_number=context.get('ticket_number', 'TEST'),
        context=context
    )
    return {"status": "test_job_queued", "job_id": job_id}


@router.get("/failures/stream")
async def print_failure_stream():
    """SSE endpoint that pushes print failure events to the UI in real time.

    The frontend can subscribe with:
        const es = new EventSource('/api/v1/print/failures/stream');
        es.onmessage = (e) => showToast(JSON.parse(e.data).error);
    """
    dispatcher = get_print_dispatcher()
    if not dispatcher:
        raise HTTPException(status_code=503, detail="Print dispatcher not running")

    q = dispatcher.subscribe_failures()

    async def _generate():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            dispatcher.unsubscribe_failures(q)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
