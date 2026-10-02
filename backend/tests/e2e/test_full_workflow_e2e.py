"""
GitReview AI — End-to-End System Integration Test Suite: Full Workflow E2E Tests.

Verifies major cross-component state transitions across authentication, repository authorization,
PR analysis orchestration, database persistence, risk & reviewer feedback, checklist completion,
user/repository analytics lifecycles, and cross-user security (IDOR) protection.

All external service boundaries (GitHub API, Gemini AI Provider) use controlled test doubles.
No real external network calls or secrets are used.
"""

from __future__ import annotations

import os

# Ensure required environment variables for test execution
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"
os.environ["STATE_SECRET"] = "test-state-secret-not-for-production"
os.environ["ENCRYPTION_KEY"] = "V1Z3dEVtN2VZZ212ZjlVemR5VnpXZWNxOHZxd0VxcTM="
os.environ["GEMINI_API_KEY"] = "fake-key-for-tests"
os.environ["GITHUB_CLIENT_ID"] = "fake-client-id"
os.environ["GITHUB_CLIENT_SECRET"] = "fake-client-secret"
os.environ["ACTIONS_SHARED_SECRET"] = "test-actions-shared-secret-12345"

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import sqlalchemy.ext.asyncio
from fastapi.testclient import TestClient
from sqlalchemy import ColumnDefault, event, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.models import (
    Base,
    Session,
)
from app.github_integration.client import PRData
from app.main import app


# Register SQLite dialect compilers for PostgreSQL types
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"

@pytest.fixture(autouse=True)
def _setup_monkeypatches(monkeypatch):
    _orig_create_async_engine = sqlalchemy.ext.asyncio.create_async_engine

    def _patched_create_async_engine(url, **kw):
        if "sqlite" in str(url):
            kw.pop("pool_size", None)
            kw.pop("max_overflow", None)
        return _orig_create_async_engine(url, **kw)

    monkeypatch.setattr(sqlalchemy.ext.asyncio, "create_async_engine", _patched_create_async_engine)

    import app.repositories.service

    async def _patched_upsert_access(db, user_id, repository_id, permission):
        from datetime import UTC, datetime

        from app.core.models import RepositoryAccess

        result = await db.execute(
            select(RepositoryAccess).where(
                RepositoryAccess.user_id == user_id,
                RepositoryAccess.repository_id == repository_id
            )
        )
        access = result.scalar_one_or_none()
        if access is None:
            access = RepositoryAccess(
                user_id=user_id,
                repository_id=repository_id,
                github_permission_level=permission,
                authorized_at=datetime.now(UTC),
                revoked_at=None
            )
            db.add(access)
        else:
            access.github_permission_level = permission
            access.authorized_at = datetime.now(UTC)
            access.revoked_at = None

        await db.flush()
        return access

    monkeypatch.setattr(app.repositories.service, "_upsert_access", _patched_upsert_access)

    _orig_httpx_get = httpx.AsyncClient.get

    async def _smart_httpx_get(self, url, *args, **kwargs):
        url_str = str(url)
        if "api.github.com" in url_str:
            parts = url_str.split("/")
            repo_name = parts[-1] if len(parts) > 0 and parts[-1] else "api"
            owner = parts[-2] if len(parts) > 1 and parts[-2] else "acme"
            from unittest.mock import MagicMock
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": 999001,
                "owner": {"login": owner},
                "name": repo_name,
                "default_branch": "main",
            }
            return mock_resp
        return await _orig_httpx_get(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", _smart_httpx_get)

# Shared test database engine using in-memory SQLite with StaticPool
# Shared test database engine using in-memory SQLite with StaticPool
_test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_test_engine.sync_engine, "connect")
def _setup_sqlite_functions(dbapi_connection, connection_record):
    dbapi_connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
    dbapi_connection.create_function("now", 0, lambda: datetime.now(UTC).isoformat())
    dbapi_connection.create_function("char_length", 1, lambda s: len(s) if s is not None else 0)


@event.listens_for(Session, "load")
def _ensure_session_timezone(target, context):
    if target.expires_at and target.expires_at.tzinfo is None:
        target.expires_at = target.expires_at.replace(tzinfo=UTC)
    if target.revoked_at and target.revoked_at.tzinfo is None:
        target.revoked_at = target.revoked_at.replace(tzinfo=UTC)


# Attach Python-side defaults for SQLite DDL compatibility
for _table in Base.metadata.tables.values():
    for _col in _table.columns:
        if _col.primary_key and str(_col.type).startswith("UUID"):
            _col.default = ColumnDefault(uuid.uuid4)
        if _col.server_default is not None:
            _arg = str(getattr(_col.server_default.arg, "text", _col.server_default.arg))
            if "gen_random_uuid" in _arg or "now" in _arg:
                _col.server_default = None
        if _col.name in ("created_at", "updated_at", "authorized_at", "completed_at") and _col.default is None:
            _col.default = ColumnDefault(lambda: datetime.now(UTC))

_TestAsyncSessionLocal = async_sessionmaker(
    bind=_test_engine, class_=AsyncSession, expire_on_commit=False
)


async def _override_get_db():
    async with _TestAsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture(autouse=True)
async def _setup_e2e_db():
    """Reset database tables before each test for complete test isolation."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def e2e_client():
    """FastAPI TestClient with get_db overridden to use the in-memory test database."""
    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


MOCK_VALID_AI_RESPONSE = json.dumps({
    "summary": "Comprehensive analysis of PR #42 modifying backend authentication endpoints.",
    "risk_tier": "medium",
    "ai_risk_signal": "medium",
    "self_reported_confidence": 85,
    "risk_rationale": {
        "summary": "Moderate risk PR modifying backend auth endpoints.",
        "factors": [
            {
                "factor": "API Changes",
                "source": "ai",
                "detail": "Modifies endpoints",
                "category": "api_changes",
                "impact": "medium",
            }
        ],
    },
    "reviewer_signals": {
        "summary": "Recommended reviewer assigned.",
        "suggested_reviewers": [
            {
                "username": "senior_dev",
                "confidence": 90,
                "rationale": "Expert in auth",
            }
        ],
    },
    "review_suggestions": [
        {
            "focus_area": "auth_flow",
            "rationale": "Verify token expiration",
            "suggested_file": "src/app.py",
        }
    ],
    "checklist": [
        {
            "category": "security",
            "item": "Verify token revocation",
            "relevant": True,
            "self_reported_confidence": 90,
            "suggested_file": "src/app.py",
        },
        {
            "category": "performance",
            "item": "Check DB query execution time",
            "relevant": True,
            "self_reported_confidence": 85,
        },
        {
            "category": "exception_handling",
            "item": "Ensure exceptions yield 401",
            "relevant": True,
            "self_reported_confidence": 88,
        },
        {
            "category": "null_handling",
            "item": "Check nullable token header",
            "relevant": True,
            "self_reported_confidence": 90,
        },
        {
            "category": "logging",
            "item": "Verify audit logs do not leak secrets",
            "relevant": True,
            "self_reported_confidence": 95,
        },
        {
            "category": "testing",
            "item": "Add E2E tests for auth flow",
            "relevant": True,
            "self_reported_confidence": 90,
        },
        {
            "category": "documentation",
            "item": "Update OpenAPI specs",
            "relevant": True,
            "self_reported_confidence": 80,
        },
        {
            "category": "dependencies",
            "item": "Check dependency versions",
            "relevant": True,
            "self_reported_confidence": 85,
        },
        {
            "category": "database_changes",
            "item": "Check migration status",
            "relevant": True,
            "self_reported_confidence": 85,
        },
    ],
})


def _create_authenticated_user_session(
    client: TestClient, username: str = "e2e_user", github_id: int = 10001
) -> tuple[str, str]:
    """Helper to register user session via OAuth callback and return (session_token, user_id)."""
    res_login = client.get("/api/auth/login")
    state = res_login.json()["state"]

    with patch("app.auth.service.exchange_code_for_token", AsyncMock(return_value="tok_mock_123")), patch(
        "app.auth.service.fetch_github_user",
        AsyncMock(return_value={"id": github_id, "login": username, "avatar_url": "https://avatar.com/u"}),
    ):
        res_cb = client.get(
            f"/api/auth/callback?code=mock_code&state={state}",
            headers={"x-oauth-state": state},
        )
    assert res_cb.status_code == 200
    token = res_cb.json()["session_token"]
    user_id = res_cb.json()["user"]["id"]
    return token, user_id


# ==============================================================================
# FLOW 1 — AUTHENTICATION / SESSION
# ==============================================================================


def test_e2e_oauth_login_initiates_flow(e2e_client: TestClient) -> None:
    """GET /api/auth/login returns GitHub authorization URL and signed CSRF state."""
    response = e2e_client.get("/api/auth/login")
    assert response.status_code == 200
    data = response.json()
    assert "authorize_url" in data
    assert "github.com/login/oauth/authorize" in data["authorize_url"]
    assert "state" in data
    assert len(data["state"]) > 10


def test_e2e_oauth_callback_creates_user_and_session(e2e_client: TestClient) -> None:
    """OAuth callback verifies state, creates User and Session in DB, returns session_token."""
    res_login = e2e_client.get("/api/auth/login")
    state = res_login.json()["state"]

    with patch("app.auth.service.exchange_code_for_token", AsyncMock(return_value="tok_123")), patch(
        "app.auth.service.fetch_github_user",
        AsyncMock(return_value={"id": 88811, "login": "alice", "avatar_url": "https://avatar.com/alice"}),
    ):
        response = e2e_client.get(
            f"/api/auth/callback?code=mock_code&state={state}",
            headers={"x-oauth-state": state},
        )

    assert response.status_code == 200
    data = response.json()
    assert "session_token" in data
    assert data["user"]["github_username"] == "alice"

    # Verify session token works for authenticated profile fetch
    me_resp = e2e_client.get("/api/auth/me", headers={"x-session-token": data["session_token"]})
    assert me_resp.status_code == 200
    assert me_resp.json()["github_username"] == "alice"


def test_e2e_oauth_callback_rejects_invalid_state(e2e_client: TestClient) -> None:
    """OAuth callback with state mismatch returns 401 Unauthorized."""
    response = e2e_client.get(
        "/api/auth/callback?code=mock_code&state=invalid_state_string",
        headers={"x-oauth-state": "different_state_string"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "oauth_error"


def test_e2e_unauthenticated_me_request_rejected(e2e_client: TestClient) -> None:
    """Unauthenticated GET /api/auth/me returns 401 Unauthorized."""
    response = e2e_client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "missing_session_token"


def test_e2e_authenticated_me_request_accepted(e2e_client: TestClient) -> None:
    """Authenticated GET /api/auth/me with valid session token returns user profile."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "bob", 88822)

    response = e2e_client.get("/api/auth/me", headers={"x-session-token": session_token})
    assert response.status_code == 200
    assert response.json()["github_username"] == "bob"


def test_e2e_logout_revokes_session(e2e_client: TestClient) -> None:
    """POST /api/auth/logout revokes session in DB; subsequent requests return 401."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "charlie", 88833)

    # Logout
    logout_resp = e2e_client.post("/api/auth/logout", headers={"x-session-token": session_token})
    assert logout_resp.status_code == 200

    # Subsequent request fails
    me_resp = e2e_client.get("/api/auth/me", headers={"x-session-token": session_token})
    assert me_resp.status_code == 401
    assert me_resp.json()["detail"]["error"] == "session_revoked"


# ==============================================================================
# FLOW 2 — REPOSITORY + PR ANALYSIS INTEGRATION & PERSISTENCE
# ==============================================================================


def test_e2e_authorize_repository_persists_access(e2e_client: TestClient) -> None:
    """POST /api/repositories/authorize creates Repository and RepositoryAccess records in DB."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "dev1", 77701)
    headers = {"x-session-token": session_token}

    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        response = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "backend-api"},
            headers=headers,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["repository"]["full_name"] == "acme/backend-api"
    assert data["access"]["is_active"] is True

    # Verify repository appears in GET /api/repositories
    list_resp = e2e_client.get("/api/repositories", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1
    assert list_resp.json()["repositories"][0]["repository"]["full_name"] == "acme/backend-api"


def test_e2e_analyze_pull_request_orchestration_and_persistence(
    e2e_client: TestClient,
) -> None:
    """Full PR analysis workflow orchestrates AI analysis and persists entities to DB."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "dev2", 77702)
    headers = {"x-session-token": session_token}

    # Authorize repository
    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        auth_resp = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "core-service"},
            headers=headers,
        )
    repo_id = auth_resp.json()["repository"]["id"]

    # Trigger PR Analysis
    mock_pr = PRData(
        repo_owner="acme",
        repo_name="core-service",
        github_repo_id=999001,
        pr_number=101,
        pr_title="PR #101: Add Feature X",
        author_username="contributor1",
        base_branch="main",
        head_branch="feature/x",
        commit_sha="b" * 40,
        state="open",
        changed_files=["src/app.py"],
        diff_text="diff --git a/src/app.py b/src/app.py\n+lines",
        lines_added=15,
        lines_removed=2,
        commit_messages=["feat: add feature x"],
    )

    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)), patch(
        "app.ai_provider.gemini_adapter.GeminiAdapter.generate", AsyncMock(return_value=MOCK_VALID_AI_RESPONSE)
    ):
        response = e2e_client.post(
            f"/api/repositories/{repo_id}/pulls/101/analyze",
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["risk_tier"] == "medium"
    assert len(data["checklist_items"]) > 0
    assert data["risk_assessment_id"] is not None
    assert data["analysis_id"] is not None


# ==============================================================================
# FLOW 3 — RISK FEEDBACK LOOP
# ==============================================================================


def test_e2e_submit_valid_risk_feedback(e2e_client: TestClient) -> None:
    """POST /api/analyses/{id}/feedback persists feedback record in DB."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "dev3", 77703)
    headers = {"x-session-token": session_token}

    # Setup repo and analysis
    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        auth_resp = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "service-a"},
            headers=headers,
        )
    repo_id = auth_resp.json()["repository"]["id"]

    mock_pr = PRData(
        repo_owner="acme",
        repo_name="service-a",
        github_repo_id=999001,
        pr_number=5,
        pr_title="PR #5",
        author_username="author1",
        base_branch="main",
        head_branch="patch-1",
        commit_sha="c" * 40,
        state="open",
        changed_files=["src/main.py"],
        diff_text="diff --git a/src/main.py b/src/main.py",
        lines_added=10,
        lines_removed=1,
    )

    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)), patch(
        "app.ai_provider.gemini_adapter.GeminiAdapter.generate", AsyncMock(return_value=MOCK_VALID_AI_RESPONSE)
    ):
        analyze_resp = e2e_client.post(
            f"/api/repositories/{repo_id}/pulls/5/analyze", headers=headers
        )

    analysis_id = analyze_resp.json()["analysis_id"]
    risk_assessment_id = analyze_resp.json()["risk_assessment_id"]

    # Submit risk feedback
    fb_resp = e2e_client.post(
        f"/api/analyses/{analysis_id}/feedback",
        json={
            "prediction_type": "risk_tier",
            "prediction_reference_id": risk_assessment_id,
            "rating": "helpful",
            "comment": "Accurate risk assessment.",
        },
        headers=headers,
    )
    assert fb_resp.status_code == 200
    fb_data = fb_resp.json()
    assert fb_data["analysis_id"] == analysis_id
    assert fb_data["rating"] == "helpful"


def test_e2e_submit_invalid_feedback_rejected(e2e_client: TestClient) -> None:
    """Submitting feedback with non-existent prediction_reference_id is rejected."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "dev4", 77704)
    headers = {"x-session-token": session_token}

    # Setup repo and analysis
    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        auth_resp = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "service-b"},
            headers=headers,
        )
    repo_id = auth_resp.json()["repository"]["id"]

    mock_pr = PRData(
        repo_owner="acme",
        repo_name="service-b",
        github_repo_id=999001,
        pr_number=8,
        pr_title="PR #8",
        author_username="author2",
        base_branch="main",
        head_branch="patch-2",
        commit_sha="d" * 40,
        state="open",
        changed_files=["src/util.py"],
        diff_text="diff --git a/src/util.py b/src/util.py",
        lines_added=5,
        lines_removed=0,
    )

    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)), patch(
        "app.ai_provider.gemini_adapter.GeminiAdapter.generate", AsyncMock(return_value=MOCK_VALID_AI_RESPONSE)
    ):
        analyze_resp = e2e_client.post(
            f"/api/repositories/{repo_id}/pulls/8/analyze", headers=headers
        )

    analysis_id = analyze_resp.json()["analysis_id"]
    fake_uuid = str(uuid.uuid4())

    # Submit feedback with fake reference ID
    fb_resp = e2e_client.post(
        f"/api/analyses/{analysis_id}/feedback",
        json={
            "prediction_type": "risk_tier",
            "prediction_reference_id": fake_uuid,
            "rating": "helpful",
        },
        headers=headers,
    )
    assert fb_resp.status_code >= 400


def test_e2e_submit_reviewer_recommendation_feedback(e2e_client: TestClient) -> None:
    """POST /api/analyses/{id}/feedback validates reviewer_recommendation prediction type."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "dev5", 77705)
    headers = {"x-session-token": session_token}

    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        auth_resp = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "service-c"},
            headers=headers,
        )
    repo_id = auth_resp.json()["repository"]["id"]

    mock_pr = PRData(
        repo_owner="acme",
        repo_name="service-c",
        github_repo_id=999001,
        pr_number=12,
        pr_title="PR #12",
        author_username="author3",
        base_branch="main",
        head_branch="patch-3",
        commit_sha="e" * 40,
        state="open",
        changed_files=["src/core.py"],
        diff_text="diff --git a/src/core.py b/src/core.py",
        lines_added=8,
        lines_removed=2,
    )

    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)), patch(
        "app.ai_provider.gemini_adapter.GeminiAdapter.generate", AsyncMock(return_value=MOCK_VALID_AI_RESPONSE)
    ):
        analyze_resp = e2e_client.post(
            f"/api/repositories/{repo_id}/pulls/12/analyze", headers=headers
        )

    analysis_id = analyze_resp.json()["analysis_id"]
    fake_rec_id = str(uuid.uuid4())

    fb_resp = e2e_client.post(
        f"/api/analyses/{analysis_id}/feedback",
        json={
            "prediction_type": "reviewer_recommendation",
            "prediction_reference_id": fake_rec_id,
            "rating": "unhelpful",
            "comment": "Reviewer was unavailable.",
        },
        headers=headers,
    )
    assert fb_resp.status_code >= 400


# ==============================================================================
# FLOW 4 — CHECKLIST COMPLETION LOOP
# ==============================================================================


def test_e2e_checklist_item_completion_toggle(e2e_client: TestClient) -> None:
    """PATCH /api/analyses/{id}/checklist/{item_id} toggles item completion in DB."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "dev6", 77706)
    headers = {"x-session-token": session_token}

    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        auth_resp = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "service-d"},
            headers=headers,
        )
    repo_id = auth_resp.json()["repository"]["id"]

    mock_pr = PRData(
        repo_owner="acme",
        repo_name="service-d",
        github_repo_id=999001,
        pr_number=20,
        pr_title="PR #20",
        author_username="author4",
        base_branch="main",
        head_branch="patch-4",
        commit_sha="f" * 40,
        state="open",
        changed_files=["src/app.py"],
        diff_text="diff --git a/src/app.py b/src/app.py",
        lines_added=12,
        lines_removed=0,
    )

    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)), patch(
        "app.ai_provider.gemini_adapter.GeminiAdapter.generate", AsyncMock(return_value=MOCK_VALID_AI_RESPONSE)
    ):
        analyze_resp = e2e_client.post(
            f"/api/repositories/{repo_id}/pulls/20/analyze", headers=headers
        )

    analysis_data = analyze_resp.json()
    analysis_id = analysis_data["analysis_id"]
    checklist_item_id = analysis_data["checklist_items"][0]["id"]

    # Toggle completion = True
    patch1 = e2e_client.patch(
        f"/api/analyses/{analysis_id}/checklist/{checklist_item_id}",
        json={"completed": True},
        headers=headers,
    )
    assert patch1.status_code == 200
    assert patch1.json()["completed"] is True

    # Re-analyze PR (cached analysis returns hydrated completed state)
    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)):
        reanalyze_resp = e2e_client.post(
            f"/api/repositories/{repo_id}/pulls/20/analyze", headers=headers
        )
    items = reanalyze_resp.json()["checklist_items"]
    target_item = next(i for i in items if i["id"] == checklist_item_id)
    assert target_item["completed"] is True

    # Toggle completion = False
    patch2 = e2e_client.patch(
        f"/api/analyses/{analysis_id}/checklist/{checklist_item_id}",
        json={"completed": False},
        headers=headers,
    )
    assert patch2.status_code == 200
    assert patch2.json()["completed"] is False


# ==============================================================================
# FLOW 6 — DASHBOARD / ANALYTICS LIFECYCLE & REVOCATION
# ==============================================================================


def test_e2e_analytics_lifecycle_and_repo_revocation(e2e_client: TestClient) -> None:
    """User and Repo analytics reflect active state, and revocation blocks subsequent access."""
    session_token, _user_id = _create_authenticated_user_session(e2e_client, "owner1", 77707)
    headers = {"x-session-token": session_token}

    # Authorize repo and analyze PR
    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        auth_resp = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "analytics-repo"},
            headers=headers,
        )
    repo_id = auth_resp.json()["repository"]["id"]

    mock_pr = PRData(
        repo_owner="acme",
        repo_name="analytics-repo",
        github_repo_id=999001,
        pr_number=1,
        pr_title="PR #1",
        author_username="author5",
        base_branch="main",
        head_branch="patch-5",
        commit_sha="1" * 40,
        state="open",
        changed_files=["src/app.py"],
        diff_text="diff --git a/src/app.py b/src/app.py",
        lines_added=5,
        lines_removed=1,
    )

    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)), patch(
        "app.ai_provider.gemini_adapter.GeminiAdapter.generate", AsyncMock(return_value=MOCK_VALID_AI_RESPONSE)
    ):
        e2e_client.post(f"/api/repositories/{repo_id}/pulls/1/analyze", headers=headers)

    # Check User Analytics
    user_analytics = e2e_client.get("/api/analytics/me", headers=headers)
    assert user_analytics.status_code == 200
    assert user_analytics.json()["total_analyses"] == 1

    # Check Repo Analytics
    repo_analytics = e2e_client.get(f"/api/analytics/repositories/{repo_id}", headers=headers)
    assert repo_analytics.status_code == 200
    assert repo_analytics.json()["total_analyses"] == 1

    # Revoke repo access
    revoke_resp = e2e_client.delete(f"/api/repositories/{repo_id}/access", headers=headers)
    assert revoke_resp.status_code == 200

    # Repo Analytics returns 404 after revocation
    repo_analytics_after = e2e_client.get(
        f"/api/analytics/repositories/{repo_id}", headers=headers
    )
    assert repo_analytics_after.status_code == 404


# ==============================================================================
# FLOW 8 — CROSS-USER SECURITY / IDOR ISOLATION
# ==============================================================================


def test_e2e_cross_user_isolation(e2e_client: TestClient) -> None:
    """User B cannot access or modify User A's repositories, analytics, or checklist items."""
    user_a_token, _user_a_id = _create_authenticated_user_session(e2e_client, "user_a", 90001)
    user_b_token, _user_b_id = _create_authenticated_user_session(e2e_client, "user_b", 90002)

    headers_a = {"x-session-token": user_a_token}
    headers_b = {"x-session-token": user_b_token}

    # User A authorizes repository and creates analysis
    with patch("app.repositories.service.GitHubApiClient.verify_repo_access", AsyncMock(return_value=(True, "admin"))):
        auth_resp_a = e2e_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "private-repo"},
            headers=headers_a,
        )
    repo_a_id = auth_resp_a.json()["repository"]["id"]

    mock_pr = PRData(
        repo_owner="acme",
        repo_name="private-repo",
        github_repo_id=999001,
        pr_number=50,
        pr_title="PR #50",
        author_username="user_a",
        base_branch="main",
        head_branch="patch-50",
        commit_sha="9" * 40,
        state="open",
        changed_files=["src/secret.py"],
        diff_text="diff --git a/src/secret.py b/src/secret.py",
        lines_added=10,
        lines_removed=0,
    )

    with patch("app.pull_requests.service.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=mock_pr)), patch(
        "app.ai_provider.gemini_adapter.GeminiAdapter.generate", AsyncMock(return_value=MOCK_VALID_AI_RESPONSE)
    ):
        analyze_resp_a = e2e_client.post(
            f"/api/repositories/{repo_a_id}/pulls/50/analyze", headers=headers_a
        )

    analysis_id = analyze_resp_a.json()["analysis_id"]
    checklist_item_id = analyze_resp_a.json()["checklist_items"][0]["id"]

    # 1. User B attempts to view User A's repository list -> User A's repo NOT in User B's list
    list_b = e2e_client.get("/api/repositories", headers=headers_b)
    assert list_b.status_code == 200
    assert list_b.json()["total"] == 0

    # 2. User B attempts to view User A's repo analytics -> 404 (IDOR / anti-enumeration)
    repo_analytics_b = e2e_client.get(
        f"/api/analytics/repositories/{repo_a_id}", headers=headers_b
    )
    assert repo_analytics_b.status_code == 404

    # 3. User B attempts to revoke User A's repository access -> 404
    revoke_b = e2e_client.delete(f"/api/repositories/{repo_a_id}/access", headers=headers_b)
    assert revoke_b.status_code == 404

    # 4. User B attempts to patch User A's checklist completion -> 404
    chk_b = e2e_client.patch(
        f"/api/analyses/{analysis_id}/checklist/{checklist_item_id}",
        json={"completed": True},
        headers=headers_b,
    )
    assert chk_b.status_code == 404
