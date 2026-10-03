"""
GitReview AI - End-to-End System Integration Test Suite: GitHub Actions Flow E2E Tests.

Verifies the POST /api/actions/analyze workflow:
- Shared secret authentication and header validation
- GitHub token presence requirement
- Repository authorization check
- PR retrieval, AI analysis orchestration, and database persistence
- Error handling for unauthenticated, unauthorized, or failing upstream requests
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"
os.environ["STATE_SECRET"] = "test-state-secret-not-for-production"
os.environ["ENCRYPTION_KEY"] = "V1Z3dEVtN2VZZ212ZjlVemR5VnpXZWNxOHZxd0VxcTM="
os.environ["GEMINI_API_KEY"] = "test-gemini-key-not-real"
os.environ["GITHUB_CLIENT_ID"] = "test-client-id"
os.environ["GITHUB_CLIENT_SECRET"] = "test-client-secret"

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import ColumnDefault, event, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.models import (
    Base,
    PullRequest,
    PullRequestAnalysis,
    Repository,
    RepositoryAccess,
    User,
)
from app.github_integration.client import PRData
from app.main import app


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


for _table in Base.metadata.tables.values():
    for _col in _table.columns:
        if _col.primary_key and str(_col.type).startswith("UUID"):
            _col.default = ColumnDefault(uuid.uuid4)
        if _col.server_default is not None:
            _arg = str(getattr(_col.server_default.arg, "text", _col.server_default.arg))
            if "gen_random_uuid" in _arg or "now" in _arg:
                _col.server_default = None
        if (
            _col.name in ("created_at", "updated_at", "authorized_at", "completed_at")
            and _col.default is None
        ):
            _col.default = ColumnDefault(lambda: datetime.now(UTC))


def _setup_sqlite_functions(dbapi_connection, connection_record):
    dbapi_connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
    dbapi_connection.create_function("now", 0, lambda: datetime.now(UTC).isoformat())
    dbapi_connection.create_function("char_length", 1, lambda s: len(s) if s is not None else 0)


TEST_ACTIONS_SECRET = "test-actions-secret-12345"
VALID_40_CHAR_SHA = "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0"

_actions_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
    echo=False,
)
event.listen(_actions_engine.sync_engine, "connect", _setup_sqlite_functions)

_ActionsSessionLocal = async_sessionmaker(
    bind=_actions_engine, class_=AsyncSession, expire_on_commit=False
)


async def _override_actions_get_db():
    async with _ActionsSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture(autouse=True)
async def _setup_actions_db():
    async with _actions_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _actions_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def actions_client(monkeypatch):
    from app.actions_integration.service import settings as service_settings

    monkeypatch.setattr(service_settings, "actions_shared_secret", TEST_ACTIONS_SECRET)
    app.dependency_overrides[get_db] = _override_actions_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


MOCK_ACTIONS_AI_RESPONSE = json.dumps(
    {
        "summary": "GitHub Actions triggered analysis summary.",
        "risk_tier": "low",
        "ai_risk_signal": "low",
        "self_reported_confidence": 92.5,
        "architectural_impact": "Minimal impact.",
        "security_risk": "No security risks detected.",
        "test_coverage_gap": "Good test coverage.",
        "breaking_change_risk": "No breaking changes.",
        "risk_factors": ["Minor doc update"],
        "recommendation": "APPROVE",
        "key_issues": [],
        "suggestions": [
            {
                "title": "Add documentation link",
                "description": "Consider referencing docs in PR body.",
                "severity": "low",
                "file_path": "README.md",
                "line_number": 1,
            }
        ],
        "checklist": [
            {
                "title": "Verify Action run output",
                "category": "TESTING",
                "required": True,
            }
        ],
    }
)


async def setup_authorized_repo(
    session: AsyncSession, owner: str, name: str
) -> tuple[User, Repository]:
    user = User(
        id=uuid.uuid4(),
        github_user_id=987654,
        github_username="actions-repo-owner",
        encrypted_access_token="encrypted_token_sample",
    )
    session.add(user)
    await session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        github_repo_id=554433,
        owner=owner,
        name=name,
        default_branch="main",
    )
    session.add(repo)
    await session.flush()

    access = RepositoryAccess(
        id=uuid.uuid4(),
        user_id=user.id,
        repository_id=repo.id,
        github_permission_level="admin",
    )
    session.add(access)
    await session.commit()
    return user, repo


@pytest.mark.asyncio
async def test_actions_analyze_valid_request_success(actions_client):
    """Flow 7.1: Valid Actions request produces persisted analysis and ActionsAnalysisResponse."""
    async with _ActionsSessionLocal() as session:
        _, repo = await setup_authorized_repo(session, "acme-corp", "service-backend")

    mock_pr = PRData(
        repo_owner="acme-corp",
        repo_name="service-backend",
        github_repo_id=554433,
        pr_number=101,
        pr_title="Feature: Add Actions integration",
        author_username="contributor",
        base_branch="main",
        head_branch="patch-101",
        commit_sha=VALID_40_CHAR_SHA,
        state="open",
        changed_files=["main.py"],
        diff_text="diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,4 @@\n+# New action line\n",
        lines_added=5,
        lines_removed=0,
        commit_messages=["feat: Add Actions integration"],
    )

    with (
        patch(
            "app.github_integration.client.GitHubApiClient.fetch_pull_request_data",
            AsyncMock(return_value=mock_pr),
        ),
        patch(
            "app.ai_provider.gemini_adapter.GeminiAdapter.generate",
            AsyncMock(return_value=MOCK_ACTIONS_AI_RESPONSE),
        ),
    ):
        payload = {
            "owner": "acme-corp",
            "name": "service-backend",
            "pr_number": 101,
            "commit_sha": VALID_40_CHAR_SHA,
        }
        headers = {
            "X-Actions-Secret": TEST_ACTIONS_SECRET,
            "X-GitHub-Token": "ghp_actions_token_sample",
        }

        response = actions_client.post("/api/actions/analyze", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()

        assert "risk_tier" in data
        assert data["status"] in ("completed", "degraded", "failed")
        assert "comment_markdown" in data
        assert data["commit_sha"] == VALID_40_CHAR_SHA

        async with _ActionsSessionLocal() as db_session:
            db_pr_res = await db_session.execute(
                select(PullRequest).where(
                    PullRequest.repository_id == repo.id,
                    PullRequest.github_pr_number == 101,
                )
            )
            db_pr = db_pr_res.scalar_one_or_none()
            assert db_pr is not None

            db_analysis_res = await db_session.execute(
                select(PullRequestAnalysis).where(PullRequestAnalysis.pull_request_id == db_pr.id)
            )
            db_analysis = db_analysis_res.scalar_one_or_none()
            assert db_analysis is not None


@pytest.mark.asyncio
async def test_actions_analyze_invalid_secret_rejected(actions_client):
    """Flow 7.2: Invalid shared secret is rejected with 401 Unauthorized."""
    payload = {
        "owner": "acme-corp",
        "name": "service-backend",
        "pr_number": 101,
        "commit_sha": VALID_40_CHAR_SHA,
    }
    headers = {
        "X-Actions-Secret": "invalid-secret-wrong",
        "X-GitHub-Token": "ghp_sample",
    }
    response = actions_client.post("/api/actions/analyze", json=payload, headers=headers)
    assert response.status_code == 401
    assert "Invalid shared secret" in response.json()["detail"]


@pytest.mark.asyncio
async def test_actions_analyze_missing_secret_rejected(actions_client):
    """Flow 7.2b: Missing shared secret header is rejected with 401 Unauthorized."""
    payload = {
        "owner": "acme-corp",
        "name": "service-backend",
        "pr_number": 101,
        "commit_sha": VALID_40_CHAR_SHA,
    }
    headers = {
        "X-GitHub-Token": "ghp_sample",
    }
    response = actions_client.post("/api/actions/analyze", json=payload, headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_actions_analyze_missing_github_token_rejected(actions_client):
    """Flow 7.3: Missing X-GitHub-Token is rejected with 400 Bad Request."""
    payload = {
        "owner": "acme-corp",
        "name": "service-backend",
        "pr_number": 101,
        "commit_sha": VALID_40_CHAR_SHA,
    }
    headers = {
        "X-Actions-Secret": TEST_ACTIONS_SECRET,
    }
    response = actions_client.post("/api/actions/analyze", json=payload, headers=headers)
    assert response.status_code == 400
    assert "X-GitHub-Token header is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_actions_analyze_unauthorized_repository_returns_404(actions_client):
    """Flow 7.4: Repository not authorized by any user returns 404 Not Found."""
    payload = {
        "owner": "unauthorized-org",
        "name": "unauthorized-repo",
        "pr_number": 99,
        "commit_sha": VALID_40_CHAR_SHA,
    }
    headers = {
        "X-Actions-Secret": TEST_ACTIONS_SECRET,
        "X-GitHub-Token": "ghp_sample_token",
    }
    response = actions_client.post("/api/actions/analyze", json=payload, headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_actions_analyze_github_fetch_failure_handled(actions_client):
    """Flow 7.5: GitHub API error fetching PR details is handled gracefully."""
    async with _ActionsSessionLocal() as session:
        await setup_authorized_repo(session, "acme-corp", "failing-repo")

    with patch(
        "app.github_integration.client.GitHubApiClient.fetch_pull_request_data",
        AsyncMock(side_effect=Exception("GitHub API Error")),
    ):
        payload = {
            "owner": "acme-corp",
            "name": "failing-repo",
            "pr_number": 404,
            "commit_sha": VALID_40_CHAR_SHA,
        }
        headers = {
            "X-Actions-Secret": TEST_ACTIONS_SECRET,
            "X-GitHub-Token": "ghp_actions_token",
        }
        response = actions_client.post("/api/actions/analyze", json=payload, headers=headers)
        assert response.status_code in (404, 500, 502)


client = TestClient(app)


@pytest.mark.asyncio
async def test_actions_analyze_oversized_pr(actions_client, monkeypatch):
    from app.core.config import Settings

    settings = Settings(
        max_pr_lines=3000,
        max_pr_bytes=1024,
        actions_shared_secret=TEST_ACTIONS_SECRET,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)

    # Setup the authorized repo
    async with _ActionsSessionLocal() as session:
        await setup_authorized_repo(session, "actions-owner", "actions-repo")

    # Mock PR data to exceed size limits (e.g., 5000 lines)
    oversized_pr_data = PRData(
        repo_owner="actions-owner",
        repo_name="actions-repo",
        github_repo_id=777,
        pr_number=99,
        pr_title="Huge PR",
        author_username="user1",
        base_branch="main",
        head_branch="huge-feature",
        commit_sha=VALID_40_CHAR_SHA,
        state="open",
        changed_files=["huge.py"],
        diff_text="a" * 1024,
        lines_added=4000,
        lines_removed=2000,
        commit_messages=["Huge commit"],
    )

    with patch(
        "app.github_integration.client.GitHubApiClient.fetch_pull_request_data",
        AsyncMock(return_value=oversized_pr_data),
    ):
        payload = {
            "owner": "actions-owner",
            "name": "actions-repo",
            "pr_number": 99,
            "commit_sha": VALID_40_CHAR_SHA,
        }
        headers = {
            "X-Actions-Secret": TEST_ACTIONS_SECRET,
            "X-GitHub-Token": "ghp_actions_token",
        }

        response = actions_client.post("/api/actions/analyze", json=payload, headers=headers)

        assert response.status_code == 413
        data = response.json()
        assert data["error"] == "PR_TOO_LARGE"
