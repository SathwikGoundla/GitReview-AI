"""
GitReview AI — Repository Authorization Router (LLD A.4)

Endpoints:
  GET    /api/repositories                          — list authorized repos
  POST   /api/repositories/authorize               — authorize a new repo
  DELETE /api/repositories/{repository_id}/access  — revoke access to a repo

HTTP method rationale:
  GET    /api/repositories             — read-only, idempotent, no body
  POST   /api/repositories/authorize  — creates/updates state (authorization record)
  DELETE /api/repositories/{id}/access — removes access (soft-delete via revoked_at)

Authorization:
  Every route requires a valid X-Session-Token (get_current_user dependency).
  User isolation is enforced at the service layer: no user can see or modify
  another user's repository access records.

Security:
  - The client supplies owner+name for authorization, never a pre-known repository_id.
    The server fetches the canonical github_repo_id from GitHub after verifying access.
  - Responses never expose OAuth tokens, session hashes, or encrypted credentials.
  - GitHubError and RepositoryNotFoundError map to structured HTTP responses via the
    global GitReviewError handler registered in main.py.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    GitHubError,
    RepositoryAccessDeniedError,
    RepositoryNotFoundError,
)
from app.core.models import User
from app.repositories.schemas import (
    AuthorizedRepositoryItem,
    AuthorizeRepositoryRequest,
    AuthorizeRepositoryResponse,
    RepositoryAccessResponse,
    RepositoryListResponse,
    RepositoryResponse,
    RevokeAccessResponse,
)
from app.repositories.service import (
    authorize_repository,
    list_authorized_repositories,
    revoke_repository_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


# ── GET /api/repositories ─────────────────────────────────────────────────────


@router.get(
    "",
    response_model=RepositoryListResponse,
    summary="List authorized repositories",
    description=(
        "Returns repositories the current user has authorized for GitReview AI analysis. "
        "Only the calling user's own authorizations are returned — never another user's."
    ),
)
async def list_repositories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RepositoryListResponse:
    """
    Return all repositories the current user has active (non-revoked) access to.
    """
    rows = await list_authorized_repositories(db, current_user)

    items = [
        AuthorizedRepositoryItem(
            repository=RepositoryResponse.from_orm_with_full_name(repo),
            access=RepositoryAccessResponse.from_orm(access),
        )
        for repo, access in rows
    ]

    return RepositoryListResponse(repositories=items, total=len(items))


# ── POST /api/repositories/authorize ─────────────────────────────────────────


@router.post(
    "/authorize",
    response_model=AuthorizeRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Authorize a repository",
    description=(
        "Authorize a GitHub repository for GitReview AI analysis. "
        "The server verifies the current user's real GitHub access before persisting. "
        "Authorizing an already-authorized repository is idempotent (returns 201 again). "
        "The owner and name must match a repository the current user can access on GitHub."
    ),
)
async def authorize_repo(
    body: AuthorizeRepositoryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthorizeRepositoryResponse:
    """
    Authorize a repository for the current user.
    Verifies GitHub access, upserts Repository + RepositoryAccess records.
    """
    try:
        repository, access = await authorize_repository(
            db=db,
            user=current_user,
            owner=body.owner,
            repo_name=body.name,
        )
    except RepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": exc.error_code, "message": exc.message},
        ) from exc
    except RepositoryAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": exc.error_code, "message": exc.message},
        ) from exc
    except GitHubError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": exc.error_code, "message": exc.message},
        ) from exc

    return AuthorizeRepositoryResponse(
        repository=RepositoryResponse.from_orm_with_full_name(repository),
        access=RepositoryAccessResponse.from_orm(access),
    )


# ── DELETE /api/repositories/{repository_id}/access ──────────────────────────


@router.delete(
    "/{repository_id}/access",
    response_model=RevokeAccessResponse,
    summary="Revoke access to a repository",
    description=(
        "Revoke the current user's GitReview AI access to a repository. "
        "Only the calling user's access is revoked — other users' access is unaffected. "
        "The repository record itself is never deleted. "
        "Revoking already-revoked access is idempotent."
    ),
)
async def revoke_access(
    repository_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevokeAccessResponse:
    """
    Soft-delete the current user's RepositoryAccess record (set revoked_at).
    """
    try:
        await revoke_repository_access(db=db, user=current_user, repository_id=repository_id)
    except RepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": exc.error_code, "message": exc.message},
        ) from exc

    return RevokeAccessResponse(repository_id=repository_id)
