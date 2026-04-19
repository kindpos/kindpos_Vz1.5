"""
Tests for `api/routes/auth.py` — PIN verification, session tokens,
rate limiting, and the role-gate dependency factory.

auth.py sat at 39% coverage. The file holds the security perimeter
that lets managers approve discounts, voids, and refunds, so it
deserves tight tests on:

  - PIN match succeeds and issues a token with role_ids
  - PIN mismatch does NOT issue a token, increments rate-limit counter
  - Rate limit kicks in after MAX_ATTEMPTS failures per window
  - Rate limit counts only failures, not successes
  - Tokens expire past TOKEN_TTL_SECONDS (monotonic-time check)
  - `get_current_session` accepts valid Bearer token, rejects everything else
  - `require_role(...)` gates sessions missing the role
  - `/auth/logout` invalidates a specific token without touching others
"""

import time
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

from app.api.routes import auth as auth_mod
from app.core.event_ledger import EventLedger
from app.core.events import EventType, create_event


TEST_DB = Path("./data/test_auth_routes.db")


@pytest_asyncio.fixture
async def ledger():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with EventLedger(str(TEST_DB)) as _ledger:
        yield _ledger
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Wipe the per-process rate-limit + session dicts between tests so one
    test's 5 failed attempts don't bleed into the next."""
    auth_mod._attempts.clear()
    auth_mod._sessions.clear()
    yield
    auth_mod._attempts.clear()
    auth_mod._sessions.clear()


def _mock_request(client_host: str = "127.0.0.1", auth_header: str = "") -> Request:
    """Minimal starlette Request carrying a client host + optional auth header.

    We construct the ASGI scope by hand because the tests only read
    `.client.host` and `.headers`, so a full TestClient is overkill.
    """
    headers = []
    if auth_header:
        headers.append((b"authorization", auth_header.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/verify-pin",
        "headers": headers,
        "client": (client_host, 9999),
    }
    return Request(scope)


async def _seed_employee(
    ledger, *, employee_id: str, pin: str, display_name: str = "Alice",
    roles: list = None, active: bool = True,
):
    """Write an EMPLOYEE_CREATED event so OverseerConfigService sees the user."""
    await ledger.append(create_event(
        event_type=EventType.EMPLOYEE_CREATED,
        terminal_id="T-TEST",
        payload={
            "employee_id": employee_id,
            "display_name": display_name,
            "first_name": display_name.split()[0] if display_name else "",
            "last_name": "",
            "pin": pin,
            "role_ids": roles or ["server"],
            "active": active,
            "hourly_rate": "0",
        },
    ))


# ═══════════════════════════════════════════════════════════════════════════
# PIN VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestVerifyPin:

    @pytest.mark.asyncio
    async def test_correct_pin_returns_token_and_roles(self, ledger):
        await _seed_employee(
            ledger, employee_id="emp_A", pin="1234",
            display_name="Alice", roles=["server", "trainer"],
        )
        res = await auth_mod.verify_pin(
            auth_mod.VerifyPinRequest(pin="1234"),
            request=_mock_request(),
            ledger=ledger,
        )
        assert res["valid"] is True
        assert res["employee_id"] == "emp_A"
        assert res["name"] == "Alice"
        assert res["roles"] == ["server", "trainer"]
        assert isinstance(res["token"], str) and len(res["token"]) >= 20

    @pytest.mark.asyncio
    async def test_wrong_pin_returns_valid_false_no_token(self, ledger):
        await _seed_employee(ledger, employee_id="emp_B", pin="5555")
        res = await auth_mod.verify_pin(
            auth_mod.VerifyPinRequest(pin="0000"),
            request=_mock_request(),
            ledger=ledger,
        )
        assert res == {"valid": False}
        # And nothing issued
        assert auth_mod._sessions == {}

    @pytest.mark.asyncio
    async def test_inactive_employee_cannot_authenticate(self, ledger):
        """An inactive employee record must not authenticate even with the
        right PIN."""
        await _seed_employee(
            ledger, employee_id="emp_C", pin="9999", active=False,
        )
        res = await auth_mod.verify_pin(
            auth_mod.VerifyPinRequest(pin="9999"),
            request=_mock_request(),
            ledger=ledger,
        )
        assert res["valid"] is False

    @pytest.mark.asyncio
    async def test_successful_auth_does_not_count_toward_rate_limit(self, ledger):
        """Legit users can sign in all day without tripping the limiter."""
        await _seed_employee(ledger, employee_id="emp_D", pin="1111")
        for _ in range(10):
            res = await auth_mod.verify_pin(
                auth_mod.VerifyPinRequest(pin="1111"),
                request=_mock_request(client_host="192.0.2.10"),
                ledger=ledger,
            )
            assert res["valid"] is True
        assert auth_mod._attempts["192.0.2.10"] == []


# ═══════════════════════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════════

class TestRateLimit:

    @pytest.mark.asyncio
    async def test_429_after_max_failed_attempts(self, ledger):
        """Five failures within the window from one client → 429 on the sixth."""
        await _seed_employee(ledger, employee_id="emp_E", pin="1234")
        req = _mock_request(client_host="10.0.0.1")

        for i in range(auth_mod.MAX_ATTEMPTS):
            res = await auth_mod.verify_pin(
                auth_mod.VerifyPinRequest(pin="0000"),
                request=req, ledger=ledger,
            )
            assert res == {"valid": False}

        # Sixth attempt — even a correct PIN is blocked while the window is hot.
        with pytest.raises(HTTPException) as exc:
            await auth_mod.verify_pin(
                auth_mod.VerifyPinRequest(pin="1234"),
                request=req, ledger=ledger,
            )
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limit_is_per_client(self, ledger):
        """One bad actor at 10.0.0.1 doesn't lock out another host."""
        await _seed_employee(ledger, employee_id="emp_F", pin="2222")

        for _ in range(auth_mod.MAX_ATTEMPTS):
            await auth_mod.verify_pin(
                auth_mod.VerifyPinRequest(pin="0000"),
                request=_mock_request(client_host="10.0.0.2"),
                ledger=ledger,
            )

        # Different client — should still be able to try.
        res = await auth_mod.verify_pin(
            auth_mod.VerifyPinRequest(pin="2222"),
            request=_mock_request(client_host="10.0.0.3"),
            ledger=ledger,
        )
        assert res["valid"] is True

    @pytest.mark.asyncio
    async def test_rate_limit_window_expires(self, ledger, monkeypatch):
        """Failed attempts older than WINDOW_SECONDS don't count."""
        await _seed_employee(ledger, employee_id="emp_G", pin="3333")

        # Fake "now" so we can fast-forward without actually sleeping
        t = [1000.0]
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: t[0])

        for _ in range(auth_mod.MAX_ATTEMPTS):
            await auth_mod.verify_pin(
                auth_mod.VerifyPinRequest(pin="0000"),
                request=_mock_request(client_host="10.0.0.4"),
                ledger=ledger,
            )

        # Next failed attempt would 429
        # … until we tick the clock past the window
        t[0] += auth_mod.WINDOW_SECONDS + 1
        res = await auth_mod.verify_pin(
            auth_mod.VerifyPinRequest(pin="3333"),
            request=_mock_request(client_host="10.0.0.4"),
            ledger=ledger,
        )
        assert res["valid"] is True


# ═══════════════════════════════════════════════════════════════════════════
# SESSION TOKENS
# ═══════════════════════════════════════════════════════════════════════════

class TestSessions:

    def test_get_current_session_accepts_valid_bearer(self):
        token = auth_mod._create_token("emp_X", "Xander", ["manager"])
        req = _mock_request(auth_header=f"Bearer {token}")
        session = auth_mod.get_current_session(req)
        assert session["employee_id"] == "emp_X"
        assert session["roles"] == ["manager"]

    def test_get_current_session_rejects_missing_header(self):
        req = _mock_request()
        with pytest.raises(HTTPException) as exc:
            auth_mod.get_current_session(req)
        assert exc.value.status_code == 401

    def test_get_current_session_rejects_bogus_token(self):
        req = _mock_request(auth_header="Bearer not-a-real-token")
        with pytest.raises(HTTPException) as exc:
            auth_mod.get_current_session(req)
        assert exc.value.status_code == 401

    def test_get_current_session_rejects_non_bearer_scheme(self):
        """Only `Authorization: Bearer <t>` is honored — no Basic, no token="""
        token = auth_mod._create_token("emp_Y", "Yuki", ["server"])
        req = _mock_request(auth_header=f"Basic {token}")
        with pytest.raises(HTTPException):
            auth_mod.get_current_session(req)

    def test_token_expires_past_ttl(self, monkeypatch):
        """Tokens are hard-TTL'd at TOKEN_TTL_SECONDS (8 hours)."""
        t = [5000.0]
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: t[0])

        token = auth_mod._create_token("emp_Z", "Zed", ["server"])
        req = _mock_request(auth_header=f"Bearer {token}")
        # Before TTL — fine
        assert auth_mod.get_current_session(req)["employee_id"] == "emp_Z"

        # Past TTL — rejected
        t[0] += auth_mod.TOKEN_TTL_SECONDS + 1
        with pytest.raises(HTTPException) as exc:
            auth_mod.get_current_session(req)
        assert exc.value.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# ROLE GATE
# ═══════════════════════════════════════════════════════════════════════════

class TestRequireRole:
    """`require_role` returns a FastAPI Depends wrapper. These tests call
    the inner `_check` the same way FastAPI would after resolving the
    session dependency."""

    def _inner_check(self, *allowed_roles):
        """Extract the check function from require_role's Depends wrapper."""
        dep = auth_mod.require_role(*allowed_roles)
        # `Depends(callable)` exposes the callable via .dependency
        return dep.dependency

    def test_role_match_passes(self):
        check = self._inner_check("manager", "admin")
        assert check(session={"employee_id": "e", "name": "n", "roles": ["manager"]})

    def test_role_mismatch_403s(self):
        check = self._inner_check("admin")
        with pytest.raises(HTTPException) as exc:
            check(session={"employee_id": "e", "name": "n", "roles": ["server"]})
        assert exc.value.status_code == 403

    def test_empty_role_list_denies(self):
        """A session with no roles can never satisfy any required role."""
        check = self._inner_check("manager")
        with pytest.raises(HTTPException):
            check(session={"employee_id": "e", "name": "n", "roles": []})


# ═══════════════════════════════════════════════════════════════════════════
# LOGOUT
# ═══════════════════════════════════════════════════════════════════════════

class TestLogout:

    @pytest.mark.asyncio
    async def test_logout_invalidates_only_that_token(self):
        tok_a = auth_mod._create_token("emp_1", "One", ["server"])
        tok_b = auth_mod._create_token("emp_2", "Two", ["server"])
        assert tok_a in auth_mod._sessions
        assert tok_b in auth_mod._sessions

        await auth_mod.logout(_mock_request(auth_header=f"Bearer {tok_a}"))

        assert tok_a not in auth_mod._sessions   # evicted
        assert tok_b in auth_mod._sessions       # untouched

    @pytest.mark.asyncio
    async def test_logout_with_no_header_is_a_no_op(self):
        tok = auth_mod._create_token("emp_3", "Three", ["server"])
        res = await auth_mod.logout(_mock_request())
        assert res == {"ok": True}
        assert tok in auth_mod._sessions

    @pytest.mark.asyncio
    async def test_logout_with_unknown_token_is_a_no_op(self):
        res = await auth_mod.logout(_mock_request(auth_header="Bearer nosuchtoken"))
        assert res == {"ok": True}
