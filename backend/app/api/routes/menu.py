"""
Menu API Routes

Endpoints for menu management and retrieval.
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any

from app.api.dependencies import get_ledger
from app.core.event_ledger import EventLedger
from app.core.menu_projection import project_menu, MenuState

router = APIRouter(prefix="/menu", tags=["menu"])

@router.get("", response_model=MenuState)
async def get_menu(ledger: EventLedger = Depends(get_ledger)):
    """
    Get the complete current menu state.
    """
    # Fetch all events (or we could optimize to only menu-related events)
    events = await ledger.get_events_since(0, limit=10000)
    return project_menu(events)

@router.get("/restaurant")
async def get_restaurant(ledger: EventLedger = Depends(get_ledger)):
    """Get restaurant info."""
    menu = await get_menu(ledger)
    return menu.restaurant

@router.get("/categories")
async def get_categories(ledger: EventLedger = Depends(get_ledger)):
    """Get all categories."""
    menu = await get_menu(ledger)
    return menu.categories

@router.get("/items")
async def get_items(ledger: EventLedger = Depends(get_ledger)):
    """Get all menu items."""
    menu = await get_menu(ledger)
    return menu.items
