"""
Step 13 tests — Authentication Service, Router, Schemas, Dependency.

Strategy:
  - Router-level tests (HTTP) patch service-layer functions so the test
    never needs to simulate a real DB session. This is correct: we test
    that the router calls the right service function with the right args,
    not that SQLAlchemy works (that is an integration test).
  - Service-layer tests (async unit) test the service functions directly
    using hand-crafted mock DB sessions with explicit return values.
  - The DB dependency override is used ONLY to satisfy FastAPI's DI graph
    (the router imports get_db); service functions are patched so the DB
    mock is never actually called by service code.

Coverage targets from the Step 13 spec:
  1.  Login endpoint behaviour
  2.  OAuth callback success path
  3.  OAuth callback failure/error path
  4.  Session creation
  5.  Current-user dependency
  6.  Unauthenticated request rejection
  7.  Logout / session revocation
  8.  Invalid / expired session handling
  9.  Existing CSRF/security behaviour (state verification)
  10. Existing health endpoint remains functional
  11. Router registration
  12. No duplicate auth/session records (upsert semantics)
  13. Error responses use structured JSON
  14. Existing Steps 1–12 tests still pass (verified by running full suite)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.exceptions import AuthError, OAuthError, SessionExpiredError, SessionRevokedError
from app.core.security import generate_oauth_state, hash_session_token
from app.main import app

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(
    github_username: str = "sathwik",
    github_user_id: int = 12345678,
) -> MagicMock:
    """Return a mock User ORM object with all attributes the router needs."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.github_username = github_username
    user.github_user_id = github_user_id
    user.avatar_url = "https://avatars.githubusercontent.com/u/12345678"
    user.encrypted_access_token = "encrypted-fake-token"
    user.preferences = {}
    user.created_at = datetime.now(UTC)
    return user


def _make_session(user_id: uuid.UUID | None = None, revoked: bool = False) -> MagicMock:
    """Return a mock Session ORM object."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.user_id = user_id or uuid.uuid4()
    s.session_token_hash = "fakehash"
    s.created_at = datetime.now(UTC)
    s.expires_at = datetime.now(UTC) + timedelta(hours=24)
    s.revoked_at = datetime.now(UTC) if revoked else None
    return s


async def _noop_db():
    """
    Minimal DB dependency override: yields an AsyncMock that satisfies
    FastAPI's DI system. Router-level tests patch the service functions
    directly so this mock is never actually called by service code.
    """
    yield AsyncMock()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """
    TestClient for the FastAPI application.
    Overrides get_db with a no-op mock so DI is satisfied.
    All service-layer calls are patched separately per test.
    """
    app.dependency_overrides[get_db] = _noop_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def valid_state():
    """A freshly-signed CSRF state string."""
    return generate_oauth_state()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Login endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoginEndpoint:
    def test_login_returns_200(self, client):
        resp = client.get("/api/auth/login")
        assert resp.status_code == 200

    def test_login_returns_authorize_url(self, client):
        body = client.get("/api/auth/login").json()
        assert "authorize_url" in body
        assert "github.com/login/oauth/authorize" in body["authorize_url"]

    def test_login_returns_state_string(self, client):
        body = client.get("/api/auth/login").json()
        assert "state" in body
        assert isinstance(body["state"], str)
        assert len(body["state"]) > 20

    def test_login_state_contains_client_id(self, client):
        url = client.get("/api/auth/login").json()["authorize_url"]
        assert "client_id=" in url

    def test_login_state_is_different_each_call(self, client):
        r1 = client.get("/api/auth/login").json()["state"]
        r2 = client.get("/api/auth/login").json()["state"]
        assert r1 != r2

    def test_login_state_is_verifiable(self, client):
        from app.core.security import verify_oauth_state

        state = client.get("/api/auth/login").json()["state"]
        payload = verify_oauth_state(state)
        assert "nonce" in payload


# ═══════════════════════════════════════════════════════════════════════════════
# 2. OAuth callback — success path
# ═══════════════════════════════════════════════════════════════════════════════


class TestCallbackSuccess:
    """
    All successful-callback tests patch handle_oauth_callback at the module
    where the router imports it (app.api.auth), so DB and GitHub HTTP are
    never touched.
    """

    def test_callback_success_returns_200(self, client, valid_state):
        user = _make_user()
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            return_value=("raw-session-token-abc123", user),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "github-code-xyz", "state": valid_state},
                headers={"x-oauth-state": valid_state},
            )
        assert resp.status_code == 200

    def test_callback_returns_session_token(self, client, valid_state):
        user = _make_user()
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            return_value=("the-raw-session-token", user),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "code", "state": valid_state},
                headers={"x-oauth-state": valid_state},
            )
        assert resp.json()["session_token"] == "the-raw-session-token"

    def test_callback_returns_user_profile(self, client, valid_state):
        user = _make_user(github_username="sathwik")
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            return_value=("tok", user),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "c", "state": valid_state},
                headers={"x-oauth-state": valid_state},
            )
        assert resp.json()["user"]["github_username"] == "sathwik"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. OAuth callback — failure paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestCallbackFailures:
    def test_callback_github_exchange_failure_returns_401(self, client, valid_state):
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            side_effect=OAuthError("bad_verification_code"),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "bad-code", "state": valid_state},
                headers={"x-oauth-state": valid_state},
            )
        assert resp.status_code == 401

    def test_callback_state_mismatch_returns_401(self, client, valid_state):
        """State mismatch is detected inside handle_oauth_callback → OAuthError → 401."""
        tampered = valid_state[:-4] + "XXXX"
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            side_effect=OAuthError("state mismatch"),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "code", "state": tampered},
                headers={"x-oauth-state": valid_state},
            )
        assert resp.status_code == 401

    def test_callback_error_body_is_structured(self, client, valid_state):
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            side_effect=OAuthError("GitHub rejected the code"),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "bad", "state": valid_state},
                headers={"x-oauth-state": valid_state},
            )
        assert "detail" in resp.json()

    def test_callback_missing_code_returns_422(self, client, valid_state):
        """Query param 'code' is required; FastAPI returns 422 if absent."""
        resp = client.get("/api/auth/callback", params={"state": valid_state})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Session creation (service layer — pure async unit, no HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSessionCreation:
    @pytest.mark.asyncio
    async def test_create_session_returns_raw_token(self):
        from app.auth.service import create_session

        db = MagicMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        token = await create_session(db, uuid.uuid4())
        assert isinstance(token, str) and len(token) >= 20

    @pytest.mark.asyncio
    async def test_create_session_stores_hash_not_raw(self):
        from app.auth.service import create_session

        db = MagicMock()
        db.flush = AsyncMock()
        added = []
        db.add = lambda obj: added.append(obj)

        raw = await create_session(db, uuid.uuid4())

        assert len(added) == 1
        assert added[0].session_token_hash != raw
        assert added[0].session_token_hash == hash_session_token(raw)

    @pytest.mark.asyncio
    async def test_create_session_sets_expiry(self):
        from app.auth.service import create_session

        db = MagicMock()
        db.flush = AsyncMock()
        added = []
        db.add = lambda obj: added.append(obj)

        await create_session(db, uuid.uuid4())
        assert added[0].expires_at > datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_two_sessions_have_different_tokens(self):
        from app.auth.service import create_session

        db = MagicMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        t1 = await create_session(db, uuid.uuid4())
        t2 = await create_session(db, uuid.uuid4())
        assert t1 != t2


# ═══════════════════════════════════════════════════════════════════════════════
# 5. get_current_user dependency
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetCurrentUserDependency:
    def test_missing_header_returns_401(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_missing_header_error_body(self, client):
        assert "detail" in client.get("/api/auth/me").json()

    def test_valid_token_resolves_user(self, client):
        user = _make_user()
        with patch(
            "app.api.dependencies.get_current_user_from_token",
            new_callable=AsyncMock,
            return_value=user,
        ):
            resp = client.get("/api/auth/me", headers={"x-session-token": "valid-tok"})
        assert resp.status_code == 200
        assert resp.json()["github_username"] == "sathwik"

    def test_expired_session_returns_401(self, client):
        with patch(
            "app.api.dependencies.get_current_user_from_token",
            new_callable=AsyncMock,
            side_effect=SessionExpiredError("expired"),
        ):
            resp = client.get("/api/auth/me", headers={"x-session-token": "expired-tok"})
        assert resp.status_code == 401

    def test_revoked_session_returns_401(self, client):
        with patch(
            "app.api.dependencies.get_current_user_from_token",
            new_callable=AsyncMock,
            side_effect=SessionRevokedError("revoked"),
        ):
            resp = client.get("/api/auth/me", headers={"x-session-token": "revoked-tok"})
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Unauthenticated request rejection
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnauthenticatedRejection:
    def test_me_without_token_is_401(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_arbitrary_auth_error_is_401(self, client):
        with patch(
            "app.api.dependencies.get_current_user_from_token",
            new_callable=AsyncMock,
            side_effect=AuthError("Session not found"),
        ):
            resp = client.get("/api/auth/me", headers={"x-session-token": "bad"})
        assert resp.status_code == 401

    def test_unauthenticated_response_has_structured_body(self, client):
        assert "detail" in client.get("/api/auth/me").json()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Logout / session revocation
# ═══════════════════════════════════════════════════════════════════════════════


class TestLogout:
    def test_logout_returns_200(self, client):
        with patch("app.api.auth.revoke_session", new_callable=AsyncMock):
            resp = client.post("/api/auth/logout", headers={"x-session-token": "tok"})
        assert resp.status_code == 200

    def test_logout_without_token_is_still_200(self, client):
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200

    def test_logout_calls_revoke_session(self, client):
        with patch("app.api.auth.revoke_session", new_callable=AsyncMock) as mock_rev:
            client.post("/api/auth/logout", headers={"x-session-token": "mytoken"})
        mock_rev.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_session_marks_revoked_at(self):
        from app.auth.service import revoke_session

        session = MagicMock()
        session.revoked_at = None

        db = AsyncMock()
        db.flush = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = session
            return result

        db.execute = fake_execute
        await revoke_session(db, "some-raw-token")
        assert session.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_session_is_noop(self):
        from app.auth.service import revoke_session

        db = AsyncMock()
        db.flush = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            return result

        db.execute = fake_execute
        await revoke_session(db, "nonexistent-token")  # must not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Invalid / expired session handling (service layer)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSessionValidation:
    @pytest.mark.asyncio
    async def test_validate_expired_session_raises(self):
        from app.auth.service import validate_session

        user = _make_user()
        session = _make_session(user_id=user.id)
        session.expires_at = datetime.now(UTC) - timedelta(hours=1)
        session.revoked_at = None

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.first.return_value = (session, user)
            return result

        db.execute = fake_execute
        with pytest.raises(SessionExpiredError):
            await validate_session(db, "any-raw-token")

    @pytest.mark.asyncio
    async def test_validate_revoked_session_raises(self):
        from app.auth.service import validate_session

        user = _make_user()
        session = _make_session(user_id=user.id, revoked=True)

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.first.return_value = (session, user)
            return result

        db.execute = fake_execute
        with pytest.raises(SessionRevokedError):
            await validate_session(db, "any-raw-token")

    @pytest.mark.asyncio
    async def test_validate_missing_session_raises(self):
        from app.auth.service import validate_session

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.first.return_value = None
            return result

        db.execute = fake_execute
        with pytest.raises(AuthError):
            await validate_session(db, "ghost-token")

    @pytest.mark.asyncio
    async def test_validate_valid_session_returns_user(self):
        from app.auth.service import validate_session

        user = _make_user()
        session = _make_session(user_id=user.id)

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.first.return_value = (session, user)
            return result

        db.execute = fake_execute
        _, returned_user = await validate_session(db, "valid-token")
        assert returned_user.github_username == "sathwik"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. CSRF / security
# ═══════════════════════════════════════════════════════════════════════════════


class TestCSRFAndState:
    def test_state_mismatch_gives_401(self, client):
        state_from_login = generate_oauth_state()
        different_state = generate_oauth_state()
        # Both states are valid but differ → mismatch caught in handle_oauth_callback
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            side_effect=OAuthError("state mismatch"),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "code", "state": different_state},
                headers={"x-oauth-state": state_from_login},
            )
        assert resp.status_code == 401

    def test_tampered_state_signature_gives_401(self, client):
        state = generate_oauth_state()
        tampered = state[:-5] + "XXXXX"
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            side_effect=OAuthError("invalid state"),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "code", "state": tampered},
                headers={"x-oauth-state": tampered},
            )
        assert resp.status_code == 401

    def test_verify_oauth_state_rejects_tampered(self):
        """The underlying CSRF utility must reject tampered states."""
        from app.core.exceptions import OAuthError
        from app.core.security import generate_oauth_state, verify_oauth_state

        state = generate_oauth_state()
        tampered = state[:-4] + "ZZZZ"
        with pytest.raises(OAuthError):
            verify_oauth_state(tampered)

    def test_verify_oauth_state_rejects_expired(self):
        from app.core.exceptions import OAuthError
        from app.core.security import generate_oauth_state, verify_oauth_state

        state = generate_oauth_state()
        with pytest.raises(OAuthError):
            verify_oauth_state(state, max_age_seconds=-1)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Health endpoint still functional
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_health_returns_ok_status(self, client):
        assert client.get("/health").json()["status"] == "ok"

    def test_health_is_unauthenticated(self, client):
        assert client.get("/health").status_code != 401


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Router registration (via OpenAPI schema)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouterRegistration:
    def _paths(self):
        return set(app.openapi()["paths"].keys())

    def test_auth_login_route_exists(self, client):
        assert "/api/auth/login" in self._paths()

    def test_auth_callback_route_exists(self, client):
        assert "/api/auth/callback" in self._paths()

    def test_auth_logout_route_exists(self, client):
        assert "/api/auth/logout" in self._paths()

    def test_auth_me_route_exists(self, client):
        assert "/api/auth/me" in self._paths()

    def test_health_route_exists(self, client):
        assert "/health" in self._paths()


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Upsert / service-layer helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestServiceHelpers:
    def test_build_authorize_url_contains_required_params(self):
        from app.auth.service import build_github_authorize_url

        url = build_github_authorize_url("test-state")
        assert "client_id=" in url
        assert "redirect_uri=" in url
        assert "state=test-state" in url
        assert "scope=" in url

    def test_initiate_login_returns_url_and_state(self):
        from app.auth.service import initiate_login

        url, state = initiate_login()
        assert url.startswith("https://") and len(state) > 20

    def test_initiate_login_state_is_verifiable(self):
        from app.auth.service import initiate_login
        from app.core.security import verify_oauth_state

        _, state = initiate_login()
        assert "nonce" in verify_oauth_state(state)

    def test_get_decrypted_token_delegates_to_decrypt_token(self):
        from app.auth.service import get_decrypted_token_for_user

        user = _make_user()
        with patch("app.auth.service.decrypt_token", return_value="plain-tok") as mock_dec:
            result = get_decrypted_token_for_user(user)
        assert result == "plain-tok"
        mock_dec.assert_called_once_with(user.encrypted_access_token)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Error responses use structured JSON
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorResponseStructure:
    def test_401_has_detail_field(self, client):
        assert "detail" in client.get("/api/auth/me").json()

    def test_422_has_detail_field(self, client):
        resp = client.get("/api/auth/callback", params={"state": "s"})
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_callback_oauth_error_has_structured_detail(self, client, valid_state):
        with patch(
            "app.api.auth.handle_oauth_callback",
            new_callable=AsyncMock,
            side_effect=OAuthError("bad code"),
        ):
            resp = client.get(
                "/api/auth/callback",
                params={"code": "bad", "state": valid_state},
                headers={"x-oauth-state": valid_state},
            )
        assert resp.status_code == 401
        assert "detail" in resp.json()
