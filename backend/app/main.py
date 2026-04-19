"""
KINDpos FastAPI Application

The main entry point for the backend API.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import sys

from app.api.routes.printing import print_queue
from app.printing.print_dispatcher import PrintDispatcher
from app.config import settings
from app.api.dependencies import init_ledger, close_ledger, set_printer_manager, get_ephemeral_log, set_print_dispatcher, get_ledger
from app.services.demo_seeder import seed_demo_data_if_empty
from app.core.adapters.printer_manager import PrinterManager
from app.core.adapters.mock_thermal import MockThermalPrinter
from app.core.adapters.base_printer import PrinterConfig, PrinterType, CutType
from app.api.routes import orders
from app.api.routes import system
from app.api.routes import menu
from app.api.routes import hardware
from app.api.routes import printing
from app.api.routes import payment_routes
from app.api.routes import config
from app.api.routes import staff
from app.api.routes import reporting
from app.api.routes import server_shift
from app.api.routes import auth
from app.api.routes import sync
from app.api.routes.printing import print_queue


_dispatcher: PrintDispatcher = None

HARDWARE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hardware_config.db')


async def _init_printer_manager(ledger, ephemeral_log=None):
    """Load saved printers from hardware_config.db, fall back to mock."""
    import aiosqlite

    manager = PrinterManager(ledger, settings.terminal_id, ephemeral_log=ephemeral_log)
    printer_found = False

    if os.path.exists(HARDWARE_DB_PATH):
        try:
            async with aiosqlite.connect(HARDWARE_DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM devices WHERE type = 'printer'") as cur:
                    rows = await cur.fetchall()
                    for row in rows:
                        device = dict(row)
                        role = "kitchen" if "kitchen" in device.get("name", "").lower() else "receipt"
                        config = PrinterConfig(
                            printer_id=device["mac"],
                            name=device.get("name", "Printer"),
                            printer_type=PrinterType.THERMAL,
                            role=role,
                            connection_string=f"{device['ip']}:{device.get('port', 9100)}",
                            cut_type=CutType.PARTIAL,
                        )
                        printer = MockThermalPrinter(config)
                        await manager.register_printer(printer)
                        printer_found = True
                        print(f"  Printer loaded: {device.get('name', device['mac'])} @ {device['ip']}")
        except Exception as e:
            print(f"  Warning: could not load printers from hardware_config.db: {e}")

    if not printer_found:
        print("  No printers configured — use Settings > Hardware to scan and add printers")

    set_printer_manager(manager)
    return manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _dispatcher

    print("Starting " + settings.app_name + " v" + settings.app_version)
    print("Terminal ID: " + settings.terminal_id)
    print("Database: " + settings.database_path)

    ledger = await init_ledger()
    print("Event Ledger initialized")

    if settings.store_mode == "demo":
        await seed_demo_data_if_empty(ledger)
    else:
        print(f"Store mode: {settings.store_mode} — skipping demo seed")

    eph_log = await get_ephemeral_log()
    printer_manager = await _init_printer_manager(ledger, ephemeral_log=eph_log)
    print(f"PrinterManager initialized ({len(printer_manager._printers)} printers)")

    await print_queue.connect()
    print("Print Queue initialized")

    _dispatcher = PrintDispatcher(print_queue)
    await _dispatcher.start()
    set_print_dispatcher(_dispatcher)
    print("Print Dispatcher started")

    yield

    await _dispatcher.stop()
    await print_queue.close()
    await close_ledger()
    print("Shutdown complete")

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Nice. Dependable. Yours.",
    lifespan=lifespan,
)

# CORS middleware (allows frontend to connect)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080", "http://localhost:8000", "http://127.0.0.1:8080", "http://localhost:63342"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(orders.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(menu.router, prefix="/api/v1")
app.include_router(hardware.router, prefix="/api/v1")
app.include_router(printing.router, prefix="/api/v1")
app.include_router(payment_routes.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(reporting.router, prefix="/api/v1")
app.include_router(server_shift.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")


# Serve frontend
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'terminal')

@app.get("/api/v1/staff")
async def get_staff_list(ledger = Depends(get_ledger)):
    """Returns active employees for Overseer badge count."""
    from app.services.overseer_config_service import OverseerConfigService
    service = OverseerConfigService(ledger)
    employees = await service.get_employees()
    return [e for e in employees if e.active]


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "terminal_id": settings.terminal_id,
    }

from fastapi.responses import RedirectResponse

@app.get("/overseer")
async def overseer_redirect():
    return RedirectResponse(url="/overseer/")

overseer_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'overseer')
if os.path.exists(overseer_path):
    print(f'Serving Overseer from: {overseer_path}')
    app.mount('/overseer', StaticFiles(directory=overseer_path, html=True), name='overseer')
else:
    print(f'WARNING: Overseer not found at: {overseer_path}')

if os.path.exists(frontend_path):
    print(f'Serving frontend from: {frontend_path}')
    app.mount('/', StaticFiles(directory=frontend_path, html=True), name='frontend')
else:
    print(f'WARNING: Frontend not found at: {frontend_path}')