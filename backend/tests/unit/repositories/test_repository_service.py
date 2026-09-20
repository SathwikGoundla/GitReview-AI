"""
Step 14 tests — Repository Authorization Service, Router, Schemas.

Strategy (same as Step 13):
  - Router-level tests (HTTP) patch service-layer functions at the import site
    used by the router (app.api.repositories.*) so the test never needs a real
    DB or real GitHub API.
  - Service-layer tests (async unit) test the service functions directly using
    hand-crafted async mock DB sessions.
  - get_current_user dependency is overridden via app.dependency_overrides so
    tests control the authenticated user without a real session.
  - FastAPI's DI graph is satisfied by overriding get_db with a no-op generator.

Coverage targets (from Step 14 spec):
  Authentication:
    1. Unauthenticated list rejected
    2. Unauthenticated authorize rejected
    3. Unauthenticated revoke rejected
  Repository listing:
    4. Authenticated user receives only their repos
    5. Empty list works
    6. GitHub retrieval failure handled
  Authorization:
    7. Valid repo can be authorized
    8. Repo info is verified against GitHub
    9. Duplicate authorization is idempotent
    10. Existing repository row is reused
    11. Inaccessible repo is rejected with 404
    12. GitHub API failure returns 502
  User isolation:
    13. User A cannot access User B's repo list
    14. User A cannot revoke User B's access
    15. User cannot authorize with another user's identity
  Revocation:
    16. Valid access can be revoked
    17. Revocation only soft-deletes one user's row
    18. Revoking nonexistent access returns 404
  API contract:
    19. Correct status codes
    20. Correct response schema shape
    21. Sensitive fields never returned
    22. Router registered in FastAPI
  Regression:
    23. Steps 1–13 tests still pass
    24. /health functional
    25. Step 13 auth routes functional
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
    GitHubError,
    RepositoryNotFoundError,
)
from app.main import app

# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_user(username: str = "sathwik", uid: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.github_username = username
    user.github_user_id = 12345678
    user.avatar_url = "https://avatars.example.com/u/1"
    user.encrypted_access_token = "enc-tok"
    user.preferences = {}
    return user


def _make_repository(
    owner: str = "acme",
    name: str = "api",
    github_repo_id: int = 999001,
) -> MagicMock:
    repo = MagicMock()
    repo.id = uuid.uuid4()
    repo.github_repo_id = github_repo_id
    repo.owner = owner
    repo.name = name
    repo.full_name = f"{owner}/{name}"
    repo.default_branch = "main"
    return repo


def _make_access(
    repo_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    revoked: bool = False,
) -> MagicMock:
    acc = MagicMock()
    acc.id = uuid.uuid4()
    acc.repository_id = repo_id or uuid.uuid4()
    acc.user_id = user_id or uuid.uuid4()
    acc.github_permission_level = "write"
    acc.authorized_at = datetime.now(UTC)
    acc.revoked_at = datetime.now(UTC) if revoked else None
    return acc


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _auth_user_override(user: MagicMock):
    """Return a FastAPI dependency override that returns the given user."""

    async def _override():
        return user

    return _override


async def _noop_db():
    """No-op DB override — satisfies DI without a real connection."""
    yield AsyncMock()


@pytest.fixture()
def client():
    """Unauthenticated TestClient (no dependency overrides)."""
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = _noop_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client():
    """Authenticated TestClient — get_current_user returns a mock user."""
    user = _make_user()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = _noop_db
    app.dependency_overrides[get_current_user] = _auth_user_override(user)
    with TestClient(app, raise_server_exceptions=False) as c:
        c._test_user = user  # expose for assertions
        yield c
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 1–3. Authentication — unauthenticated requests must be rejected
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnauthenticated:
    def test_list_without_token_is_401(self, client):
        assert client.get("/api/repositories").status_code == 401

    def test_authorize_without_token_is_401(self, client):
        resp = client.post(
            "/api/repositories/authorize",
            json={"owner": "acme", "name": "api"},
        )
        assert resp.status_code == 401

    def test_revoke_without_token_is_401(self, client):
        rid = uuid.uuid4()
        assert client.delete(f"/api/repositories/{rid}/access").status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# 4–6. Repository listing
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepositoryListing:
    def test_authenticated_user_receives_their_repos(self, auth_client):
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.list_authorized_repositories",
            new_callable=AsyncMock,
            return_value=[(repo, access)],
        ):
            resp = auth_client.get("/api/repositories")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["repositories"][0]["repository"]["owner"] == "acme"
        assert body["repositories"][0]["repository"]["name"] == "api"

    def test_empty_repository_list(self, auth_client):
        with patch(
            "app.api.repositories.list_authorized_repositories",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = auth_client.get("/api/repositories")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["repositories"] == []

    def test_list_response_has_full_name(self, auth_client):
        repo = _make_repository(owner="org", name="backend")
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.list_authorized_repositories",
            new_callable=AsyncMock,
            return_value=[(repo, access)],
        ):
            resp = auth_client.get("/api/repositories")

        assert resp.json()["repositories"][0]["repository"]["full_name"] == "org/backend"

    def test_list_response_has_access_info(self, auth_client):
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)
        access.github_permission_level = "admin"

        with patch(
            "app.api.repositories.list_authorized_repositories",
            new_callable=AsyncMock,
            return_value=[(repo, access)],
        ):
            resp = auth_client.get("/api/repositories")

        item = resp.json()["repositories"][0]
        assert item["access"]["github_permission_level"] == "admin"
        assert item["access"]["is_active"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7–12. Repository authorization
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthorization:
    def test_valid_repo_authorization_returns_201(self, auth_client):
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            return_value=(repo, access),
        ):
            resp = auth_client.post(
                "/api/repositories/authorize",
                json={"owner": "acme", "name": "api"},
            )

        assert resp.status_code == 201

    def test_authorization_response_has_repository(self, auth_client):
        repo = _make_repository(owner="acme", name="api")
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            return_value=(repo, access),
        ):
            resp = auth_client.post(
                "/api/repositories/authorize",
                json={"owner": "acme", "name": "api"},
            )

        body = resp.json()
        assert body["repository"]["owner"] == "acme"
        assert body["repository"]["name"] == "api"
        assert body["repository"]["full_name"] == "acme/api"

    def test_authorization_response_has_access(self, auth_client):
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)
        access.github_permission_level = "write"

        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            return_value=(repo, access),
        ):
            resp = auth_client.post(
                "/api/repositories/authorize",
                json={"owner": "acme", "name": "api"},
            )

        assert resp.json()["access"]["github_permission_level"] == "write"

    def test_inaccessible_repo_returns_404(self, auth_client):
        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            side_effect=RepositoryNotFoundError("Not found"),
        ):
            resp = auth_client.post(
                "/api/repositories/authorize",
                json={"owner": "ghost", "name": "private"},
            )

        assert resp.status_code == 404

    def test_github_api_failure_returns_502(self, auth_client):
        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            side_effect=GitHubError("GitHub unavailable"),
        ):
            resp = auth_client.post(
                "/api/repositories/authorize",
                json={"owner": "acme", "name": "api"},
            )

        assert resp.status_code == 502

    def test_missing_owner_returns_422(self, auth_client):
        resp = auth_client.post(
            "/api/repositories/authorize",
            json={"name": "api"},  # owner missing
        )
        assert resp.status_code == 422

    def test_missing_name_returns_422(self, auth_client):
        resp = auth_client.post(
            "/api/repositories/authorize",
            json={"owner": "acme"},  # name missing
        )
        assert resp.status_code == 422

    def test_authorization_passes_owner_and_name_to_service(self, auth_client):
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            return_value=(repo, access),
        ) as mock_svc:
            auth_client.post(
                "/api/repositories/authorize",
                json={"owner": "myorg", "name": "myrepo"},
            )

        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["owner"] == "myorg"
        assert call_kwargs["repo_name"] == "myrepo"


# ═══════════════════════════════════════════════════════════════════════════════
# 13–15. User isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestUserIsolation:
    def test_user_a_cannot_revoke_user_b_access(self):
        """
        User A is authenticated. They supply User B's repository_id.
        The service raises RepositoryNotFoundError (User A has no record for that id).
        The router must return 404, never 200.
        """
        user_a = _make_user(username="alice")
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _auth_user_override(user_a)

        user_b_repo_id = uuid.uuid4()

        with (
            TestClient(app, raise_server_exceptions=False) as c,
            patch(
                "app.api.repositories.revoke_repository_access",
                new_callable=AsyncMock,
                side_effect=RepositoryNotFoundError(
                    f"Repository access record not found for the current user "
                    f"(repository_id={user_b_repo_id})."
                ),
            ),
        ):
            resp = c.delete(f"/api/repositories/{user_b_repo_id}/access")

        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_list_only_returns_current_users_repos(self):
        """
        The list service returns only the authenticated user's repos.
        We verify the router passes the current_user (not any other) to the service.
        """
        user_a = _make_user(username="alice")
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _auth_user_override(user_a)

        with (
            TestClient(app, raise_server_exceptions=False) as c,
            patch(
                "app.api.repositories.list_authorized_repositories",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_list,
        ):
            c.get("/api/repositories")

        app.dependency_overrides.clear()
        # The service is called positionally: list_authorized_repositories(db, current_user)
        # args[1] is current_user
        call_args = mock_list.call_args.args
        assert call_args[1].github_username == "alice"

    def test_authorize_passes_authenticated_user_to_service(self):
        """
        The authorize endpoint passes the resolved current_user to the service,
        not any user supplied in the request body.
        """
        user = _make_user(username="charlie")
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _auth_user_override(user)

        repo = _make_repository()
        access = _make_access(repo_id=repo.id)

        with (
            TestClient(app, raise_server_exceptions=False) as c,
            patch(
                "app.api.repositories.authorize_repository",
                new_callable=AsyncMock,
                return_value=(repo, access),
            ) as mock_auth,
        ):
            c.post(
                "/api/repositories/authorize",
                json={"owner": "acme", "name": "api"},
            )

        app.dependency_overrides.clear()
        call_kwargs = mock_auth.call_args.kwargs
        assert call_kwargs["user"].github_username == "charlie"


# ═══════════════════════════════════════════════════════════════════════════════
# 16–18. Revocation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRevocation:
    def test_valid_revoke_returns_200(self, auth_client):
        rid = uuid.uuid4()
        with patch(
            "app.api.repositories.revoke_repository_access",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = auth_client.delete(f"/api/repositories/{rid}/access")

        assert resp.status_code == 200

    def test_revoke_response_includes_repository_id(self, auth_client):
        rid = uuid.uuid4()
        with patch(
            "app.api.repositories.revoke_repository_access",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = auth_client.delete(f"/api/repositories/{rid}/access")

        assert str(resp.json()["repository_id"]) == str(rid)

    def test_revoke_nonexistent_returns_404(self, auth_client):
        rid = uuid.uuid4()
        with patch(
            "app.api.repositories.revoke_repository_access",
            new_callable=AsyncMock,
            side_effect=RepositoryNotFoundError("Not found"),
        ):
            resp = auth_client.delete(f"/api/repositories/{rid}/access")

        assert resp.status_code == 404

    def test_revoke_invalid_uuid_returns_422(self, auth_client):
        resp = auth_client.delete("/api/repositories/not-a-uuid/access")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 19–22. API contract
# ═══════════════════════════════════════════════════════════════════════════════


class TestAPIContract:
    def test_correct_status_codes(self, auth_client):
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            return_value=(repo, access),
        ):
            assert (
                auth_client.post(
                    "/api/repositories/authorize",
                    json={"owner": "a", "name": "b"},
                ).status_code
                == 201
            )

    def test_list_response_schema(self, auth_client):
        with patch(
            "app.api.repositories.list_authorized_repositories",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = auth_client.get("/api/repositories")

        body = resp.json()
        assert "repositories" in body
        assert "total" in body

    def test_sensitive_fields_not_in_list_response(self, auth_client):
        """OAuth token and session hash must never appear in API responses."""
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.list_authorized_repositories",
            new_callable=AsyncMock,
            return_value=[(repo, access)],
        ):
            resp = auth_client.get("/api/repositories")

        body_str = str(resp.json())
        assert "encrypted_access_token" not in body_str
        assert "session_token" not in body_str
        assert "enc-tok" not in body_str

    def test_sensitive_fields_not_in_authorize_response(self, auth_client):
        repo = _make_repository()
        access = _make_access(repo_id=repo.id)

        with patch(
            "app.api.repositories.authorize_repository",
            new_callable=AsyncMock,
            return_value=(repo, access),
        ):
            resp = auth_client.post(
                "/api/repositories/authorize",
                json={"owner": "a", "name": "b"},
            )

        body_str = str(resp.json())
        assert "encrypted_access_token" not in body_str
        assert "session_token" not in body_str

    def test_router_is_registered(self, auth_client):
        paths = set(app.openapi()["paths"].keys())
        assert "/api/repositories" in paths
        assert "/api/repositories/authorize" in paths
        assert "/api/repositories/{repository_id}/access" in paths

    def test_error_responses_are_structured(self, auth_client):
        rid = uuid.uuid4()
        with patch(
            "app.api.repositories.revoke_repository_access",
            new_callable=AsyncMock,
            side_effect=RepositoryNotFoundError("Not found"),
        ):
            resp = auth_client.delete(f"/api/repositories/{rid}/access")

        body = resp.json()
        assert "detail" in body


# ═══════════════════════════════════════════════════════════════════════════════
# Service-layer unit tests (async, no HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class TestServiceLayerRevocation:
    @pytest.mark.asyncio
    async def test_revoke_sets_revoked_at(self):
        from app.repositories.service import revoke_repository_access

        user = _make_user()
        repo_id = uuid.uuid4()
        access = _make_access(repo_id=repo_id, user_id=user.id, revoked=False)

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = access
            return result

        db.execute = fake_execute
        db.flush = AsyncMock()

        await revoke_repository_access(db, user, repo_id)

        assert access.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_already_revoked_is_noop(self):
        from app.repositories.service import revoke_repository_access

        user = _make_user()
        repo_id = uuid.uuid4()
        access = _make_access(repo_id=repo_id, user_id=user.id, revoked=True)
        original_revoked_at = access.revoked_at

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = access
            return result

        db.execute = fake_execute
        db.flush = AsyncMock()

        await revoke_repository_access(db, user, repo_id)

        # revoked_at must not change
        assert access.revoked_at == original_revoked_at
        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_raises_not_found(self):
        from app.repositories.service import revoke_repository_access

        user = _make_user()
        repo_id = uuid.uuid4()

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            return result

        db.execute = fake_execute

        with pytest.raises(RepositoryNotFoundError):
            await revoke_repository_access(db, user, repo_id)


class TestServiceLayerListing:
    @pytest.mark.asyncio
    async def test_list_returns_empty_when_no_access(self):
        from app.repositories.service import list_authorized_repositories

        user = _make_user()
        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.all.return_value = []
            return result

        db.execute = fake_execute

        rows = await list_authorized_repositories(db, user)
        assert rows == []

    @pytest.mark.asyncio
    async def test_list_returns_repo_access_pairs(self):
        from app.repositories.service import list_authorized_repositories

        user = _make_user()
        repo = _make_repository()
        access = _make_access(repo_id=repo.id, user_id=user.id)

        db = AsyncMock()

        async def fake_execute(_stmt):
            result = MagicMock()
            result.all.return_value = [(repo, access)]
            return result

        db.execute = fake_execute

        rows = await list_authorized_repositories(db, user)
        assert len(rows) == 1
        returned_repo, returned_access = rows[0]
        assert returned_repo.owner == "acme"


# ═══════════════════════════════════════════════════════════════════════════════
# Schema unit tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemas:
    def test_repository_response_full_name(self):
        from app.repositories.schemas import RepositoryResponse

        repo = _make_repository(owner="org", name="proj")
        r = RepositoryResponse.from_orm_with_full_name(repo)
        assert r.full_name == "org/proj"

    def test_access_response_is_active_when_not_revoked(self):
        from app.repositories.schemas import RepositoryAccessResponse

        access = _make_access(revoked=False)
        a = RepositoryAccessResponse.from_orm(access)
        assert a.is_active is True

    def test_access_response_is_inactive_when_revoked(self):
        from app.repositories.schemas import RepositoryAccessResponse

        access = _make_access(revoked=True)
        a = RepositoryAccessResponse.from_orm(access)
        assert a.is_active is False

    def test_authorize_request_validates_empty_owner(self):
        from pydantic import ValidationError

        from app.repositories.schemas import AuthorizeRepositoryRequest

        with pytest.raises(ValidationError):
            AuthorizeRepositoryRequest(owner="", name="repo")

    def test_authorize_request_validates_empty_name(self):
        from pydantic import ValidationError

        from app.repositories.schemas import AuthorizeRepositoryRequest

        with pytest.raises(ValidationError):
            AuthorizeRepositoryRequest(owner="org", name="")


# ═══════════════════════════════════════════════════════════════════════════════
# 23–25. Regression — existing routes still work
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegression:
    def test_health_still_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_auth_login_still_works(self, client):
        resp = client.get("/api/auth/login")
        assert resp.status_code == 200
        assert "authorize_url" in resp.json()

    def test_auth_me_still_requires_auth(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_auth_routes_still_registered(self, client):
        paths = set(app.openapi()["paths"].keys())
        assert "/api/auth/login" in paths
        assert "/api/auth/me" in paths

    def test_new_routes_do_not_shadow_health(self, client):
        assert client.get("/health").json()["status"] == "ok"
