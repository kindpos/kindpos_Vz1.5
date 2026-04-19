"""
KINDpos Authentication Routes

PIN verification with rate limiting and session token issuance.
"""

import time
import secrets
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.api.dependencies import get_ledger
from app.core.event_ledger import EventLedger
from app.services.overseer_config_service import OverseerConfigService

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Rate Limiting ─────────────────────────────────
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60

_attempts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(client_id: str) -> None:
    """Raise 429 if client has exceeded MAX_ATTEMPTS in the current window."""
    now = time.monotonic()
    # Prune expired entries
    _attempts[client_id] = [t for t in _attempts[client_id] if now - t < WINDOW_SECONDS]
    if len(_attempts[client_id]) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many PIN attempts. Try again in 60 seconds.",
        )


def _record_attempt(client_id: str) -> None:
    """Record a failed PIN attempt."""
    _attempts[client_id].append(time.monotonic())


# ── Session Tokens ────────────────────────────────
TOKEN_TTL_SECONDS = 8 * 60 * 60  # 8-hour shift

_sessions: dict[str, dict] = {}


def _create_token(employee_id: str, name: str, roles: list[str]) -> str:
    """Issue a new session token for an authenticated employee."""
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "employee_id": employee_id,
        "name": name,
        "roles": roles,
        "created_at": time.monotonic(),
    }
    return token


def _prune_expired_sessions() -> None:
    """Remove expired session tokens."""
    now = time.monotonic()
    expired = [t for t, s in _sessions.items() if now - s["created_at"] > TOKEN_TTL_SECONDS]
    for t in expired:
        del _sessions[t]


def get_current_session(request: Request) -> dict:
    """Dependency: extract and validate session token from Authorization header.

    Usage in other routes:
        session = Depends(get_current_session)
        # session = {"employee_id": ..., "name": ..., "roles": [...]}
    """
    _prune_expired_sessions()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        session = _sessions.get(token)
        if session and time.monotonic() - session["created_at"] < TOKEN_TTL_SECONDS:
            return session
    raise HTTPException(status_code=401, detail="Invalid or expired session")


def require_role(*allowed_roles: str):
    """Dependency factory: require the session to have at least one of the allowed roles.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("admin", "manager"))])
    """
    def _check(session: dict = Depends(get_current_session)) -> dict:
        if not any(r in session["roles"] for r in allowed_roles):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return session
    return Depends(_check)


# ── Routes ────────────────────────────────────────

class VerifyPinRequest(BaseModel):
    pin: str


@router.post("/verify-pin")
async def verify_pin(
    request_body: VerifyPinRequest,
    request: Request,
    ledger: EventLedger = Depends(get_ledger),
):
    """Verify a PIN and return the matching employee with a session token.

    Rate-limited: max 5 failed attempts per 60-second window per client.
    """
    client_id = request.client.host if request.client else "unknown"
    _check_rate_limit(client_id)

    service = OverseerConfigService(ledger)
    employees = await service.get_employees()

    for e in employees:
        if e.active and e.pin == request_body.pin:
            token = _create_token(e.employee_id, e.display_name, e.role_ids)
            return {
                "valid": True,
                "employee_id": e.employee_id,
                "name": e.display_name,
                "roles": e.role_ids,
                "token": token,
            }

    _record_attempt(client_id)
    return {"valid": False}


@router.post("/logout")
async def logout(request: Request):
    """Invalidate the current session token."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        _sessions.pop(token, None)
    return {"ok": True}
