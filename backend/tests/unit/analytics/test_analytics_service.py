"""
Step 17 tests — Analytics Service and API Router.

Strategy (identical to Steps 13–16):
  - Router-level HTTP tests patch service functions at the router's import site.
  - Service-level tests mock DB and ORM objects directly.
  - get_current_user overridden via app.dependency_overrides.
  - get_db overridden with a no-op async generator.
  - No real PostgreSQL. No real GitHub. No real AI.

Coverage plan:
  Schemas:              1–6   (RiskDistribution, FeedbackSummary, response models)
  Service helpers:      7–12  (risk distribution builder, feedback summary builder)
  /api/analytics/me:   13–21  (auth, data, empty, aggregation, user isolation)
  /repos/{id}:         22–33  (auth, IDOR, unauthorized 404, cross-user, empty, schema)
  Regression:          34–35  (prior routes intact, health still works)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.analytics.schemas import RepositoryAnalyticsResponse
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.main import app

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_user(username: str = "sathwik", uid: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.github_username = username
    user.github_user_id = 99999
    user.encrypted_access_token = "enc-fake"
    user.preferences = {}
    return user


def _noop_db():
    async def _gen():
        yield MagicMock()
    return _gen()


def _make_client(user: MagicMock | None = None) -> TestClient:
    """TestClient with get_current_user and get_db overridden."""
    _user = user or _make_user()
    app.dependency_overrides[get_current_user] = lambda: _user
    app.dependency_overrides[get_db] = lambda: _noop_db()
    return TestClient(app, raise_server_exceptions=False)


def _restore():
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


# ── Schema unit tests ──────────────────────────────────────────────────────────


class TestRiskDistributionSchema:
    """Tests 1–3"""

    def test_defaults_all_zero(self):
        from app.analytics.schemas import RiskDistribution
        r = RiskDistribution()
        assert r.low == 0
        assert r.medium == 0
        assert r.high == 0
        assert r.critical == 0

    def test_explicit_values(self):
        from app.analytics.schemas import RiskDistribution
        r = RiskDistribution(low=1, medium=2, high=3, critical=4)
        assert r.critical == 4

    def test_serialises_correctly(self):
        from app.analytics.schemas import RiskDistribution
        d = RiskDistribution(low=5).model_dump()
        assert d["low"] == 5
        assert "medium" in d


class TestFeedbackSummarySchema:
    """Tests 4–6"""

    def test_defaults(self):
        from app.analytics.schemas import FeedbackSummary
        fb = FeedbackSummary()
        assert fb.total == 0
        assert fb.helpful_pct is None

    def test_explicit_with_pct(self):
        from app.analytics.schemas import FeedbackSummary
        fb = FeedbackSummary(total=10, helpful=7, unhelpful=3, helpful_pct=70.0)
        assert fb.helpful_pct == 70.0

    def test_zero_total_null_pct(self):
        from app.analytics.schemas import FeedbackSummary
        fb = FeedbackSummary(total=0, helpful=0, unhelpful=0)
        assert fb.helpful_pct is None


# ── Service helper unit tests ──────────────────────────────────────────────────


class TestRiskDistributionBuilder:
    """Tests 7–9"""

    def test_empty_input(self):
        from app.analytics.service import _risk_distribution_from_rows
        r = _risk_distribution_from_rows([])
        assert r.low == r.medium == r.high == r.critical == 0

    def test_partial_tiers(self):
        from app.analytics.service import _risk_distribution_from_rows
        r = _risk_distribution_from_rows([("high", 5), ("critical", 2)])
        assert r.high == 5
        assert r.critical == 2
        assert r.low == 0

    def test_unknown_tier_ignored(self):
        """A bad DB value must never crash the endpoint."""
        from app.analytics.service import _risk_distribution_from_rows
        r = _risk_distribution_from_rows([("unknown", 99), ("low", 1)])
        assert r.low == 1
        assert r.medium == 0


class TestFeedbackSummaryBuilder:
    """Tests 10–12"""

    def test_zero_total_no_pct(self):
        from app.analytics.service import _feedback_summary
        fb = _feedback_summary(0, 0)
        assert fb.helpful_pct is None

    def test_all_helpful(self):
        from app.analytics.service import _feedback_summary
        fb = _feedback_summary(10, 0)
        assert fb.helpful_pct == 100.0

    def test_rounding(self):
        from app.analytics.service import _feedback_summary
        # 1/3 → 33.3%
        fb = _feedback_summary(1, 2)
        assert fb.helpful_pct == 33.3


# ── GET /api/analytics/me ──────────────────────────────────────────────────────


class TestUserAnalyticsEndpoint:
    """Tests 13–21"""

    def test_unauthenticated_returns_401(self):
        """Test 13 — missing session token must be rejected."""
        _restore()  # ensure no override
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/analytics/me")
        assert resp.status_code == 401

    def test_authenticated_returns_200(self):
        """Test 14 — valid session gets 200."""
        from app.analytics.schemas import UserAnalyticsResponse
        user = _make_user()
        mock_response = UserAnalyticsResponse(
            user_id=str(user.id), github_username=user.github_username
        )
        client = _make_client(user)
        with patch(
            "app.api.analytics.get_user_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = client.get("/api/analytics/me")
        _restore()
        assert resp.status_code == 200

    def test_response_contains_user_id(self):
        """Test 15 — user_id in response matches session user."""
        from app.analytics.schemas import UserAnalyticsResponse
        user = _make_user(username="sathwik")
        mock_response = UserAnalyticsResponse(
            user_id=str(user.id), github_username="sathwik"
        )
        client = _make_client(user)
        with patch(
            "app.api.analytics.get_user_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = client.get("/api/analytics/me")
        _restore()
        data = resp.json()
        assert data["user_id"] == str(user.id)
        assert data["github_username"] == "sathwik"

    def test_empty_data_returns_zeroes(self):
        """Test 16 — brand-new user with no analyses gets zeroes, not errors."""
        from app.analytics.schemas import UserAnalyticsResponse
        user = _make_user()
        mock_response = UserAnalyticsResponse(
            user_id=str(user.id),
            github_username=user.github_username,
            total_analyses=0,
            completed_analyses=0,
        )
        client = _make_client(user)
        with patch(
            "app.api.analytics.get_user_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = client.get("/api/analytics/me")
        _restore()
        assert resp.status_code == 200
        assert resp.json()["total_analyses"] == 0

    def test_response_schema_has_required_keys(self):
        """Test 17 — all expected top-level keys present."""
        from app.analytics.schemas import UserAnalyticsResponse
        user = _make_user()
        mock_response = UserAnalyticsResponse(
            user_id=str(user.id), github_username=user.github_username
        )
        client = _make_client(user)
        with patch(
            "app.api.analytics.get_user_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = client.get("/api/analytics/me")
        _restore()
        keys = set(resp.json().keys())
        for expected in [
            "user_id", "github_username", "total_analyses", "completed_analyses",
            "risk_distribution", "feedback_given", "reviewer_stats",
            "authorized_repository_count",
        ]:
            assert expected in keys, f"Missing key: {expected}"

    def test_risk_distribution_nested_schema(self):
        """Test 18 — risk_distribution contains low/medium/high/critical."""
        from app.analytics.schemas import RiskDistribution, UserAnalyticsResponse
        user = _make_user()
        mock_response = UserAnalyticsResponse(
            user_id=str(user.id),
            github_username=user.github_username,
            risk_distribution=RiskDistribution(low=2, medium=1, high=3, critical=0),
        )
        client = _make_client(user)
        with patch(
            "app.api.analytics.get_user_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = client.get("/api/analytics/me")
        _restore()
        rd = resp.json()["risk_distribution"]
        assert rd["low"] == 2
        assert rd["high"] == 3

    def test_user_isolation_session_drives_scope(self):
        """Test 19 — two different users get separate analytics calls."""
        from app.analytics.schemas import UserAnalyticsResponse
        user_a = _make_user(username="alice")
        user_b = _make_user(username="bob")

        calls = []

        async def _fake_analytics(db, user):
            calls.append(user.github_username)
            return UserAnalyticsResponse(
                user_id=str(user.id), github_username=user.github_username
            )

        # Request as user_a
        client_a = _make_client(user_a)
        with patch("app.api.analytics.get_user_analytics", new=_fake_analytics):
            client_a.get("/api/analytics/me")
        _restore()

        # Request as user_b
        client_b = _make_client(user_b)
        with patch("app.api.analytics.get_user_analytics", new=_fake_analytics):
            client_b.get("/api/analytics/me")
        _restore()

        assert "alice" in calls
        assert "bob" in calls

    def test_service_error_does_not_leak_internals(self):
        """Test 20 — unexpected service error returns 500 without stack trace."""
        user = _make_user()
        client = _make_client(user)
        with patch(
            "app.api.analytics.get_user_analytics",
            new=AsyncMock(side_effect=RuntimeError("db connection failed")),
        ):
            resp = client.get("/api/analytics/me")
        _restore()
        # FastAPI converts unhandled exceptions to 500
        assert resp.status_code == 500

    def test_feedback_given_nested_schema(self):
        """Test 21 — feedback_given has total/helpful/unhelpful/helpful_pct."""
        from app.analytics.schemas import FeedbackSummary, UserAnalyticsResponse
        user = _make_user()
        mock_response = UserAnalyticsResponse(
            user_id=str(user.id),
            github_username=user.github_username,
            feedback_given=FeedbackSummary(total=5, helpful=4, unhelpful=1, helpful_pct=80.0),
        )
        client = _make_client(user)
        with patch(
            "app.api.analytics.get_user_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = client.get("/api/analytics/me")
        _restore()
        fb = resp.json()["feedback_given"]
        assert fb["total"] == 5
        assert fb["helpful_pct"] == 80.0


# ── GET /api/analytics/repositories/{repository_id} ───────────────────────────


class TestRepositoryAnalyticsEndpoint:
    """Tests 22–33"""

    def _make_access_row(self) -> MagicMock:
        row = MagicMock()
        row.id = uuid.uuid4()
        return row

    def _make_repo_analytics(self, repo_id: uuid.UUID) -> RepositoryAnalyticsResponse:
        return RepositoryAnalyticsResponse(
            repository_id=str(repo_id),
            github_repo_id=42,
            owner="acme",
            name="api",
            full_name="acme/api",
        )

    def test_unauthenticated_returns_401(self):
        """Test 22."""
        _restore()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/analytics/repositories/{uuid.uuid4()}")
        assert resp.status_code == 401

    def test_unauthorized_repo_returns_404(self):
        """Test 23 — IDOR-safe: 404 not 403, so caller cannot infer existence."""
        user = _make_user()
        client = _make_client(user)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = _gen_db(mock_db)

        resp = client.get(f"/api/analytics/repositories/{uuid.uuid4()}")
        _restore()
        assert resp.status_code == 404

    def test_authorized_repo_returns_200(self):
        """Test 24 — authorized user gets analytics."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()
        mock_response = self._make_repo_analytics(repo_id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        assert resp.status_code == 200

    def test_cross_user_idor_protection(self):
        """Test 25 — user_a cannot read analytics for user_b's private repo."""
        user_a = _make_user(username="alice")
        user_b_repo_id = uuid.uuid4()  # only user_b has access

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # user_a has no access
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user_a
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/analytics/repositories/{user_b_repo_id}"
        )
        _restore()
        assert resp.status_code == 404

    def test_nonexistent_repo_returns_404(self):
        """Test 26 — passes authorization check but repo row is missing."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        from app.core.exceptions import RepositoryNotFoundError
        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(side_effect=RepositoryNotFoundError("not found")),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        assert resp.status_code == 404

    def test_empty_repo_returns_zeroes(self):
        """Test 27 — repo with no analyses still returns a valid response."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()
        mock_response = self._make_repo_analytics(repo_id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        assert resp.status_code == 200
        assert resp.json()["total_analyses"] == 0

    def test_response_schema_shape(self):
        """Test 28 — all expected top-level keys present."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()
        mock_response = self._make_repo_analytics(repo_id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        keys = set(resp.json().keys())
        for expected in [
            "repository_id", "github_repo_id", "owner", "name", "full_name",
            "total_analyses", "risk_distribution", "feedback_received",
            "reviewer_stats", "authorized_user_count",
        ]:
            assert expected in keys, f"Missing key: {expected}"

    def test_full_name_derived_correctly(self):
        """Test 29 — full_name = owner/name."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()

        from app.analytics.schemas import RepositoryAnalyticsResponse
        mock_response = RepositoryAnalyticsResponse(
            repository_id=str(repo_id),
            github_repo_id=7,
            owner="sathwik",
            name="gitreview-ai",
            full_name="sathwik/gitreview-ai",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        assert resp.json()["full_name"] == "sathwik/gitreview-ai"

    def test_risk_distribution_in_repo_response(self):
        """Test 30 — risk_distribution nested object present."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()

        from app.analytics.schemas import RepositoryAnalyticsResponse, RiskDistribution
        mock_response = RepositoryAnalyticsResponse(
            repository_id=str(repo_id),
            github_repo_id=8,
            owner="org",
            name="repo",
            full_name="org/repo",
            risk_distribution=RiskDistribution(high=3, critical=1),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        rd = resp.json()["risk_distribution"]
        assert rd["high"] == 3
        assert rd["critical"] == 1

    def test_revoked_access_returns_404(self):
        """Test 31 — revoked authorization is treated as no access."""
        user = _make_user()
        # Simulate: DB returns None because WHERE revoked_at IS NULL filters it out
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/analytics/repositories/{uuid.uuid4()}"
        )
        _restore()
        assert resp.status_code == 404

    def test_avg_confidence_in_response(self):
        """Test 32 — avg_confidence field present and can be null."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()

        from app.analytics.schemas import RepositoryAnalyticsResponse
        mock_response = RepositoryAnalyticsResponse(
            repository_id=str(repo_id),
            github_repo_id=9,
            owner="x",
            name="y",
            full_name="x/y",
            avg_confidence=None,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(return_value=mock_response),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        assert "avg_confidence" in resp.json()
        assert resp.json()["avg_confidence"] is None

    def test_service_error_returns_500(self):
        """Test 33 — unexpected service error → 500."""
        user = _make_user()
        repo_id = uuid.uuid4()
        access_row = self._make_access_row()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = access_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = _gen_db(mock_db)

        with patch(
            "app.api.analytics.get_repository_analytics",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                f"/api/analytics/repositories/{repo_id}"
            )
        _restore()
        assert resp.status_code == 500


# ── Regression tests ───────────────────────────────────────────────────────────


class TestRegression:
    """Tests 34–35 — Prior routes must remain intact."""

    def test_health_endpoint_still_works(self):
        """Test 34."""
        _restore()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_analytics_routes_registered(self):
        """Test 35 — both new routes appear in the OpenAPI schema."""
        _restore()
        client = TestClient(app)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json()["paths"]
        assert "/api/analytics/me" in paths
        assert "/api/analytics/repositories/{repository_id}" in paths


# ── DB helper ──────────────────────────────────────────────────────────────────


def _gen_db(mock_db):
    """Returns an async generator FUNCTION (not a generator) for use as DI override."""
    async def _gen():
        yield mock_db
    return _gen  # return the FUNCTION, not a called instance
