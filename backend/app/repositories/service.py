"""
GitReview AI — Repository Authorization Service (LLD A.4 / B.2)

Manages the multi-repository authorization scope: which users have enabled
which repositories for GitReview AI analysis.

Design rules:
  - All GitHub API calls use the authenticated user's own decrypted OAuth token.
    We NEVER call GitHub with a system-level credential.
  - Repository rows are shared across users who authorize the same repo.
    We upsert on github_repo_id so a repo is never duplicated.
  - RepositoryAccess is per-user: revoking User A's access never touches User B's.
  - We verify actual GitHub access before persisting any authorization record.
  - The UNIQUE(user_id, repository_id) constraint enforces idempotency at the DB level.

Field reference (from Database Validation doc):
  repositories.github_repo_id  — GitHub's own immutable numeric repo id
  repositories.owner           — login name of the repo owner (org or user)
  repositories.name            — repository name (without owner prefix)
  repositories.default_branch  — HEAD branch (nullable)
  repository_access.user_id    — FK → users.id
  repository_access.repository_id — FK → repositories.id
  repository_access.github_permission_level — CHECK('admin','maintain','write','read')
  repository_access.authorized_at — timestamp of authorization
  repository_access.revoked_at    — NULL means active; non-NULL means revoked
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import get_decrypted_token_for_user
from app.core.exceptions import (
    GitHubError,
    RepositoryNotFoundError,
)
from app.core.models import Repository, RepositoryAccess, User
from app.github_integration.client import GitHubApiClient

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _github_client_for(user: User) -> GitHubApiClient:
    """Construct a GitHubApiClient using the authenticated user's decrypted token."""
    token = get_decrypted_token_for_user(user)
    return GitHubApiClient(access_token=token)


# ── Repository upsert ─────────────────────────────────────────────────────────


async def _upsert_repository(
    db: AsyncSession,
    github_repo_id: int,
    owner: str,
    name: str,
    default_branch: str | None,
) -> Repository:
    """
    Upsert a Repository row keyed on github_repo_id.
    If the repo already exists, update owner/name/default_branch (handles renames).
    Returns the ORM Repository object.
    """
    stmt = (
        pg_insert(Repository)
        .values(
            github_repo_id=github_repo_id,
            owner=owner,
            name=name,
            default_branch=default_branch,
            updated_at=datetime.now(UTC),
        )
        .on_conflict_do_update(
            index_elements=["github_repo_id"],
            set_={
                "owner": owner,
                "name": name,
                "default_branch": default_branch,
                "updated_at": datetime.now(UTC),
            },
        )
        .returning(Repository)
    )

    result = await db.execute(stmt)
    await db.flush()

    repo = result.scalars().first()
    if repo is None:
        row = await db.execute(
            select(Repository).where(Repository.github_repo_id == github_repo_id)
        )
        repo = row.scalars().first()

    if repo is None:
        raise GitHubError("Failed to create or retrieve repository record after upsert.")

    return repo


# ── Access upsert ─────────────────────────────────────────────────────────────


async def _upsert_access(
    db: AsyncSession,
    user_id: uuid.UUID,
    repository_id: uuid.UUID,
    permission_level: str | None,
) -> RepositoryAccess:
    """
    Upsert a RepositoryAccess row for (user_id, repository_id).
    If the row already exists (even revoked), restore it as active and update
    the permission level.
    Returns the ORM RepositoryAccess object.

    The UNIQUE(user_id, repository_id) constraint means we can use ON CONFLICT
    to update idempotently — no duplicate rows ever created.
    """
    stmt = (
        pg_insert(RepositoryAccess)
        .values(
            user_id=user_id,
            repository_id=repository_id,
            github_permission_level=permission_level,
            authorized_at=datetime.now(UTC),
            revoked_at=None,
        )
        .on_conflict_do_update(
            constraint="uq_repository_access_user_repo",
            set_={
                "github_permission_level": permission_level,
                "authorized_at": datetime.now(UTC),
                "revoked_at": None,  # re-activates a previously revoked access
            },
        )
        .returning(RepositoryAccess)
    )

    result = await db.execute(stmt)
    await db.flush()

    access = result.scalars().first()
    if access is None:
        row = await db.execute(
            select(RepositoryAccess).where(
                RepositoryAccess.user_id == user_id,
                RepositoryAccess.repository_id == repository_id,
            )
        )
        access = row.scalars().first()

    if access is None:
        raise GitHubError("Failed to create or retrieve repository access record after upsert.")

    return access


# ── Public service functions ──────────────────────────────────────────────────


async def authorize_repository(
    db: AsyncSession,
    user: User,
    owner: str,
    repo_name: str,
) -> tuple[Repository, RepositoryAccess]:
    """
    Authorize a repository for GitReview AI analysis.

    Steps:
      1. Verify the authenticated user actually has GitHub access to the repo.
         (Prevents authorizing repos the user cannot see.)
      2. Upsert the Repository row (shared across users, keyed on github_repo_id).
      3. Upsert the RepositoryAccess row (per-user, idempotent).

    Returns (Repository, RepositoryAccess).
    Raises:
      RepositoryNotFoundError  — repo does not exist on GitHub or user cannot see it
      RepositoryAccessDeniedError — GitHub returns 403 (can see but cannot access)
      GitHubError              — any other GitHub API failure
    """
    client = _github_client_for(user)

    # Step 1: Verify real GitHub access
    try:
        has_access, permission_level = await client.verify_repo_access(owner, repo_name)
    except Exception as exc:
        raise GitHubError(
            f"GitHub API error while verifying access to {owner}/{repo_name}.",
            detail=str(exc),
        ) from exc

    if not has_access:
        logger.warning(
            "Repository authorization denied. user=%s repo=%s/%s",
            user.github_username,
            owner,
            repo_name,
        )
        raise RepositoryNotFoundError(
            f"Repository '{owner}/{repo_name}' was not found or is not accessible "
            "with your GitHub credentials."
        )

    # Step 2: Fetch repo metadata from GitHub to get the canonical github_repo_id
    try:
        import httpx  # noqa: PLC0415

        from app.github_integration.client import _GITHUB_API  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                f"{_GITHUB_API}/repos/{owner}/{repo_name}",
                headers={
                    "Authorization": f"Bearer {get_decrypted_token_for_user(user)}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if not resp.is_success:
            raise GitHubError(
                f"Failed to fetch repository metadata from GitHub: HTTP {resp.status_code}."
            )
        repo_data = resp.json()
    except GitHubError:
        raise
    except Exception as exc:
        raise GitHubError(
            "Unexpected error while fetching repository metadata from GitHub.",
            detail=str(exc),
        ) from exc

    github_repo_id: int = repo_data["id"]
    canonical_owner: str = repo_data["owner"]["login"]
    canonical_name: str = repo_data["name"]
    default_branch: str | None = repo_data.get("default_branch")

    # Step 3: Upsert repository and access records atomically in this session
    repository = await _upsert_repository(
        db, github_repo_id, canonical_owner, canonical_name, default_branch
    )

    access = await _upsert_access(db, user.id, repository.id, permission_level)

    logger.info(
        "Repository authorized. user=%s repo=%s/%s permission=%s",
        user.github_username,
        canonical_owner,
        canonical_name,
        permission_level,
    )

    return repository, access


async def list_authorized_repositories(
    db: AsyncSession,
    user: User,
) -> list[tuple[Repository, RepositoryAccess]]:
    """
    Return all repositories the user has currently active (non-revoked) access to.

    Uses the partial index: user_id WHERE revoked_at IS NULL.
    Only returns the calling user's own access — never another user's.
    """
    result = await db.execute(
        select(Repository, RepositoryAccess)
        .join(
            RepositoryAccess,
            RepositoryAccess.repository_id == Repository.id,
        )
        .where(
            RepositoryAccess.user_id == user.id,
            RepositoryAccess.revoked_at.is_(None),
        )
        .order_by(Repository.owner, Repository.name)
    )

    return list(result.all())


async def revoke_repository_access(
    db: AsyncSession,
    user: User,
    repository_id: uuid.UUID,
) -> None:
    """
    Revoke the calling user's access to a repository.

    Critically:
      - Only the CALLING USER's access is revoked.
      - The Repository row itself is never deleted (other users may still use it).
      - The RepositoryAccess row is soft-deleted via revoked_at timestamp.
      - Revoking a nonexistent or already-revoked access is a no-op (idempotent).

    Raises RepositoryNotFoundError if the user never had access to this repository_id.
    """
    result = await db.execute(
        select(RepositoryAccess).where(
            RepositoryAccess.user_id == user.id,
            RepositoryAccess.repository_id == repository_id,
        )
    )
    access = result.scalars().first()

    if access is None:
        # The user never authorized this repository — surface a 404.
        raise RepositoryNotFoundError(
            f"Repository access record not found for the current user "
            f"(repository_id={repository_id})."
        )

    if access.revoked_at is not None:
        # Already revoked — idempotent no-op.
        logger.info(
            "Repository access already revoked. user=%s repository_id=%s",
            user.github_username,
            repository_id,
        )
        return

    access.revoked_at = datetime.now(UTC)
    await db.flush()

    logger.info(
        "Repository access revoked. user=%s repository_id=%s",
        user.github_username,
        repository_id,
    )
