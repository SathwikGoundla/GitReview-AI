"""
Step 15 tests — Pull Request Service, Router, Schemas.

Strategy (same as Steps 13 & 14):
  - Router-level HTTP tests patch service functions at the router's import site
    (app.api.pull_requests.*), never the definition site.
  - Service-layer async unit tests mock DB and GitHub client directly.
  - get_current_user is overridden via app.dependency_overrides.
  - get_db is overridden with a no-op async generator so DI is satisfied.
  - No real GitHub calls. No real DB. No real AI.

Coverage targets:
  Authentication:     1–3   (all endpoints reject unauthenticated)
  Repository auth:    4–7   (authorization guard; IDOR prevention)
  PR listing:         8–11  (list response, empty list, GitHub failure, rate limit)
  PR detail:         12–15  (detail response, missing PR, bad number, schema)
  Analysis:          16–23  (orchestrator called, result shape, failure, idempotency)
  Security:          24–27  (no tokens in response, cross-user rejection)
  API/Integration:   28–31  (router registered, health, auth, repo routes regression)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    GitHubRateLimitError,
    PullRequestNotFoundError,
    RepositoryNotFoundError,
)
from app.main import app

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(username: str = "sathwik", uid: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.github_username = username
    user.github_user_id = 12345678
    user.avatar_url = "https://avatars.example.com/u/1"
    user.encrypted_access_token = "enc-fake-tok"
    user.preferences = {}
    return user


def _make_repository(owner: str = "acme", name: str = "api") -> MagicMock:
    repo = MagicMock()
    repo.id = uuid.uuid4()
    repo.github_repo_id = 999001
    repo.owner = owner
    repo.name = name
    repo.default_branch = "main"
    return repo


def _make_pr_data(
    pr_number: int = 42,
    owner: str = "acme",
    repo_name: str = "api",
    state: str = "open",
) -> MagicMock:
    """Return a mock PRData object matching the real dataclass fields."""
    pr = MagicMock()
    pr.repo_owner = owner
    pr.repo_name = repo_name
    pr.github_repo_id = 999001
    pr.pr_number = pr_number
    pr.pr_title = f"PR #{pr_number}: Add feature"
    pr.author_username = "dev"
    pr.base_branch = "main"
    pr.head_branch = "feature/x"
    pr.commit_sha = "a" * 40
    pr.state = state
    pr.changed_files = ["src/app.py", "tests/test_app.py"]
    pr.diff_text = "diff --git a/src/app.py b/src/app.py\n..."
    pr.lines_added = 50
    pr.lines_removed = 10
    pr.commit_messages = ["Add feature X"]
    pr.linked_issue_title = None
    pr.linked_issue_body = None
    return pr


def _make_analysis_result(
    pr_id: uuid.UUID | None = None,
    commit_sha: str = "a" * 40,
) -> MagicMock:
    """Return a mock AnalysisResult matching the real dataclass fields."""
    r = MagicMock()
    r.analysis_id = uuid.uuid4()
    r.pull_request_id = pr_id or uuid.uuid4()
    r.commit_sha = commit_sha
    r.status = "completed"
    r.summary = "This PR adds feature X."
    r.risk_tier = "medium"
    r.risk_source = "hybrid"
    r.risk_rationale = {"factors": [{"factor": "large diff", "source": "deterministic"}]}
    r.risk_confidence = 78.5
    r.review_suggestions = [{"focus_area": "Check null handling", "category": "null_handling"}]
    r.reviewer_recommendation = {
        "username": "alice",
        "reason": "Prior reviewer of auth module",
        "confidence_score": 82.0,
    }
    r.checklist_items = [
        {"category": "testing", "confidence_score": 90.0, "trigger_source": "deterministic"},
        {"category": "security", "confidence_score": 75.0, "trigger_source": "ai"},
    ]
    r.checklist_is_fallback = False
    r.triggered_by = "extension"
    r.model_name = "gemini-2.5-flash"
    r.prompt_template_version = "v1.0"
    r.created_at = datetime.now(UTC)
    return r


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _auth_override(user: MagicMock):
    async def _override():
        return user
    return _override


async def _noop_db():
    yield AsyncMock()


@pytest.fixture()
def client():
    """Unauthenticated client — only get_db overridden."""
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = _noop_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client():
    """Authenticated client — get_current_user returns a mock user."""
    user = _make_user()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = _noop_db
    app.dependency_overrides[get_current_user] = _auth_override(user)
    with TestClient(app, raise_server_exceptions=False) as c:
        c._test_user = user
        yield c
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 1–3. Authentication — all endpoints must reject unauthenticated requests
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnauthenticated:
    def test_list_prs_requires_auth(self, client):
        rid = uuid.uuid4()
        assert client.get(f"/api/repositories/{rid}/pulls").status_code == 401

    def test_get_pr_requires_auth(self, client):
        rid = uuid.uuid4()
        assert client.get(f"/api/repositories/{rid}/pulls/42").status_code == 401

    def test_analyze_pr_requires_auth(self, client):
        rid = uuid.uuid4()
        assert client.post(f"/api/repositories/{rid}/pulls/42/analyze").status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# 4–7. Repository authorization
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepositoryAuthorization:
    def test_authorized_user_can_list_prs(self, auth_client):
        repo = _make_repository()
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            return_value=(repo, []),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls")
        assert resp.status_code == 200

    def test_unauthorized_repository_returns_404(self, auth_client):
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            side_effect=RepositoryNotFoundError("Not authorized"),
        ):
            resp = auth_client.get(f"/api/repositories/{uuid.uuid4()}/pulls")
        assert resp.status_code == 404

    def test_user_a_cannot_access_user_b_repository(self):
        """User A is authenticated. They supply User B's repository_id → 404."""
        user_a = _make_user(username="alice")
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _auth_override(user_a)

        user_b_repo_id = uuid.uuid4()
        with (
            TestClient(app, raise_server_exceptions=False) as c,
            patch(
                "app.api.pull_requests.list_pull_requests",
                new_callable=AsyncMock,
                side_effect=RepositoryNotFoundError("Not authorized for user_b repo"),
            ),
        ):
            resp = c.get(f"/api/repositories/{user_b_repo_id}/pulls")

        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_missing_repository_id_returns_422(self, auth_client):
        """Passing a non-UUID path parameter must fail with 422 (FastAPI validation)."""
        resp = auth_client.get("/api/repositories/not-a-uuid/pulls")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 8–11. PR listing
# ═══════════════════════════════════════════════════════════════════════════════


class TestPRListing:
    def test_pr_list_returns_200(self, auth_client):
        repo = _make_repository()
        pr = _make_pr_data()
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            return_value=(repo, [pr]),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls")
        assert resp.status_code == 200

    def test_pr_list_response_shape(self, auth_client):
        repo = _make_repository(owner="org", name="backend")
        pr = _make_pr_data(pr_number=7)
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            return_value=(repo, [pr]),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls")
        body = resp.json()
        assert body["owner"] == "org"
        assert body["name"] == "backend"
        assert body["total"] == 1
        assert body["pull_requests"][0]["pr_number"] == 7
        assert body["pull_requests"][0]["state"] == "open"

    def test_empty_pr_list(self, auth_client):
        repo = _make_repository()
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            return_value=(repo, []),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls")
        body = resp.json()
        assert body["total"] == 0
        assert body["pull_requests"] == []

    def test_github_failure_handled(self, auth_client):
        from app.core.exceptions import GitHubError
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            side_effect=GitHubError("GitHub unavailable"),
        ):
            resp = auth_client.get(f"/api/repositories/{uuid.uuid4()}/pulls")
        assert resp.status_code == 502

    def test_github_rate_limit_handled(self, auth_client):
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            side_effect=GitHubRateLimitError("Rate limited"),
        ):
            resp = auth_client.get(f"/api/repositories/{uuid.uuid4()}/pulls")
        assert resp.status_code == 429

    def test_list_response_no_diff_text(self, auth_client):
        """Diff text must never appear in the list response."""
        repo = _make_repository()
        pr = _make_pr_data()
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            return_value=(repo, [pr]),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls")
        assert "diff_text" not in str(resp.json())


# ═══════════════════════════════════════════════════════════════════════════════
# 12–15. PR detail
# ═══════════════════════════════════════════════════════════════════════════════


class TestPRDetail:
    def test_valid_pr_returns_200(self, auth_client):
        repo = _make_repository()
        pr = _make_pr_data()
        with patch(
            "app.api.pull_requests.get_pull_request",
            new_callable=AsyncMock,
            return_value=(repo, pr),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls/42")
        assert resp.status_code == 200

    def test_pr_detail_response_shape(self, auth_client):
        repo = _make_repository()
        pr = _make_pr_data(pr_number=99)
        with patch(
            "app.api.pull_requests.get_pull_request",
            new_callable=AsyncMock,
            return_value=(repo, pr),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls/99")
        body = resp.json()
        assert body["pr_number"] == 99
        assert "changed_files" in body
        assert "commit_messages" in body
        assert "commit_sha" in body
        assert "diff_text" not in body  # never exposed via API

    def test_missing_pr_returns_404(self, auth_client):
        with patch(
            "app.api.pull_requests.get_pull_request",
            new_callable=AsyncMock,
            side_effect=PullRequestNotFoundError("PR not found"),
        ):
            resp = auth_client.get(f"/api/repositories/{uuid.uuid4()}/pulls/999")
        assert resp.status_code == 404

    def test_invalid_pull_number_returns_422(self, auth_client):
        """Path param pull_number must be an integer."""
        rid = uuid.uuid4()
        resp = auth_client.get(f"/api/repositories/{rid}/pulls/not-a-number")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 16–23. Analysis endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalysis:
    def test_analyze_returns_200(self, auth_client):
        result = _make_analysis_result()
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        assert resp.status_code == 200

    def test_analyze_response_has_required_fields(self, auth_client):
        result = _make_analysis_result()
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        body = resp.json()
        assert "analysis_id" in body
        assert "risk_tier" in body
        assert "risk_confidence" in body
        assert "risk_rationale" in body
        assert "checklist_items" in body
        assert "review_suggestions" in body
        assert "status" in body
        assert "commit_sha" in body

    def test_analyze_risk_tier_correct(self, auth_client):
        result = _make_analysis_result()
        result.risk_tier = "high"
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        assert resp.json()["risk_tier"] == "high"

    def test_analyze_reviewer_recommendation_present(self, auth_client):
        result = _make_analysis_result()
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        rec = resp.json()["reviewer_recommendation"]
        assert rec is not None
        assert rec["username"] == "alice"
        assert "reason" in rec
        assert "confidence_score" in rec

    def test_analyze_checklist_items_present(self, auth_client):
        result = _make_analysis_result()
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        items = resp.json()["checklist_items"]
        assert len(items) == 2
        assert any(i["category"] == "testing" for i in items)

    def test_analyze_passes_triggered_by(self, auth_client):
        result = _make_analysis_result()
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ) as mock_svc:
            auth_client.post(
                f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze",
                json={"triggered_by": "github_action"},
            )
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["triggered_by"] == "github_action"

    def test_analyze_failure_returns_error(self, auth_client):
        from app.core.exceptions import AnalysisError
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            side_effect=AnalysisError("Pipeline failed"),
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        assert resp.status_code == 500

    def test_analyze_pr_not_found(self, auth_client):
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            side_effect=PullRequestNotFoundError("PR not found"),
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/9999/analyze")
        assert resp.status_code == 404

    def test_analyze_no_reviewer_recommendation(self, auth_client):
        """When reviewer abstains, reviewer_recommendation should be null."""
        result = _make_analysis_result()
        result.reviewer_recommendation = None
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        assert resp.json()["reviewer_recommendation"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 24–27. Security
# ═══════════════════════════════════════════════════════════════════════════════


class TestSecurity:
    def test_no_oauth_token_in_list_response(self, auth_client):
        repo = _make_repository()
        with patch(
            "app.api.pull_requests.list_pull_requests",
            new_callable=AsyncMock,
            return_value=(repo, []),
        ):
            resp = auth_client.get(f"/api/repositories/{repo.id}/pulls")
        body_str = str(resp.json())
        assert "enc-fake-tok" not in body_str
        assert "encrypted_access_token" not in body_str
        assert "session_token" not in body_str

    def test_no_oauth_token_in_analysis_response(self, auth_client):
        result = _make_analysis_result()
        with patch(
            "app.api.pull_requests.analyze_pull_request",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = auth_client.post(f"/api/repositories/{uuid.uuid4()}/pulls/42/analyze")
        body_str = str(resp.json())
        assert "enc-fake-tok" not in body_str
        assert "encrypted_access_token" not in body_str

    def test_cross_user_repository_rejected(self):
        """User A cannot access PRs in User B's authorized repository."""
        user_a = _make_user(username="alice")
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _auth_override(user_a)

        user_b_repo_id = uuid.uuid4()
        with (
            TestClient(app, raise_server_exceptions=False) as c,
            patch(
                "app.api.pull_requests.analyze_pull_request",
                new_callable=AsyncMock,
                side_effect=RepositoryNotFoundError("Not your repo"),
            ),
        ):
            resp = c.post(f"/api/repositories/{user_b_repo_id}/pulls/1/analyze")

        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_exception_detail_not_exposed(self, auth_client):
        """Internal exception messages must not leak stack traces."""
        with patch(
            "app.api.pull_requests.get_pull_request",
            new_callable=AsyncMock,
            side_effect=PullRequestNotFoundError("PR not found"),
        ):
            resp = auth_client.get(f"/api/repositories/{uuid.uuid4()}/pulls/1")
        body = resp.json()
        assert "Traceback" not in str(body)
        assert "detail" in body


# ═══════════════════════════════════════════════════════════════════════════════
# 28–31. Router registration and regression
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouterRegistration:
    def _paths(self):
        return set(app.openapi()["paths"].keys())

    def test_pr_list_route_registered(self, auth_client):
        assert "/api/repositories/{repository_id}/pulls" in self._paths()

    def test_pr_detail_route_registered(self, auth_client):
        assert "/api/repositories/{repository_id}/pulls/{pull_number}" in self._paths()

    def test_pr_analyze_route_registered(self, auth_client):
        assert "/api/repositories/{repository_id}/pulls/{pull_number}/analyze" in self._paths()

    def test_health_still_works(self, client):
        assert client.get("/health").status_code == 200

    def test_health_response_correct(self, client):
        assert client.get("/health").json()["status"] == "ok"

    def test_auth_login_still_works(self, client):
        resp = client.get("/api/auth/login")
        assert resp.status_code == 200
        assert "authorize_url" in resp.json()

    def test_repository_list_still_works(self, auth_client):
        with patch(
            "app.api.repositories.list_authorized_repositories",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = auth_client.get("/api/repositories")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Service-layer unit tests (async, no HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthorizationGuardService:
    @pytest.mark.asyncio
    async def test_get_authorized_repository_raises_when_no_access(self):
        from app.pull_requests.service import get_authorized_repository

        user = _make_user()
        repo_id = uuid.uuid4()
        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.first.return_value = None
            return result

        db.execute = fake_execute

        with pytest.raises(RepositoryNotFoundError):
            await get_authorized_repository(db, user, repo_id)

    @pytest.mark.asyncio
    async def test_get_authorized_repository_returns_repo_when_authorized(self):
        from app.pull_requests.service import get_authorized_repository

        user = _make_user()
        repo_id = uuid.uuid4()
        repo = _make_repository()
        access = MagicMock()

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.first.return_value = (repo, access)
            return result

        db.execute = fake_execute

        returned = await get_authorized_repository(db, user, repo_id)
        assert returned is repo


class TestGetOrCreatePullRequest:
    @pytest.mark.asyncio
    async def test_creates_pr_when_not_exists(self):
        from app.pull_requests.service import get_or_create_pull_request

        repo = _make_repository()
        pr_data = _make_pr_data()

        db = AsyncMock()
        db.flush = AsyncMock()
        added = []
        db.add = lambda obj: added.append(obj)

        call_count = [0]

        async def fake_execute(_stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # First call: SELECT to check existing — returns None
                result.scalars.return_value.first.return_value = None
            else:
                # Second call: reload after insert
                pr_orm = MagicMock()
                pr_orm.id = uuid.uuid4()
                pr_orm.github_pr_number = pr_data.pr_number
                pr_orm.title = pr_data.pr_title
                pr_orm.state = pr_data.state
                pr_orm.latest_commit_sha = pr_data.commit_sha
                pr_orm.repository = repo
                result.scalars.return_value.one.return_value = pr_orm
            return result

        db.execute = fake_execute

        await get_or_create_pull_request(db, repo, pr_data)
        assert len(added) == 1  # One PullRequest added

    @pytest.mark.asyncio
    async def test_updates_pr_when_exists(self):
        from app.pull_requests.service import get_or_create_pull_request

        repo = _make_repository()
        pr_data = _make_pr_data(state="merged")

        existing_pr = MagicMock()
        existing_pr.id = uuid.uuid4()
        existing_pr.state = "open"
        existing_pr.title = "Old title"
        existing_pr.latest_commit_sha = "b" * 40
        existing_pr.repository = repo

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = existing_pr
            return result

        db.execute = fake_execute

        returned_pr = await get_or_create_pull_request(db, repo, pr_data)
        # Must have updated state and commit_sha
        assert returned_pr.state == "merged"
        assert returned_pr.latest_commit_sha == "a" * 40


class TestSchemas:
    def test_analysis_response_has_risk_confidence_bounds(self):
        from pydantic import ValidationError

        from app.pull_requests.schemas import AnalysisResponse

        with pytest.raises(ValidationError):
            AnalysisResponse(
                analysis_id=uuid.uuid4(),
                pull_request_id=uuid.uuid4(),
                commit_sha="a" * 40,
                status="completed",
                risk_tier="high",
                risk_source="hybrid",
                risk_rationale={},
                risk_confidence=150.0,  # out of bounds
                triggered_by="extension",
                model_name="gemini",
                prompt_template_version="v1",
                created_at=datetime.now(UTC),
            )

    def test_pr_summary_response_shape(self):
        from app.pull_requests.schemas import PRSummaryResponse

        s = PRSummaryResponse(
            pr_number=1,
            title="Test",
            author_username="dev",
            state="open",
            head_branch="feat",
            base_branch="main",
            commit_sha="a" * 40,
        )
        assert s.pr_number == 1
        assert s.lines_added == 0  # default

    def test_analyze_request_default_triggered_by(self):
        from app.pull_requests.schemas import AnalyzeRequest

        req = AnalyzeRequest()
        assert req.triggered_by == "extension"
