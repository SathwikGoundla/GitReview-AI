"""
GitReview AI — Analytics Router (LLD A.18 / SRS FR-9)

Endpoints:
  GET /api/analytics/me
      Aggregate analytics for the authenticated user (SRS FR-9.1).
      No query parameters — user is derived from the session.

  GET /api/analytics/repositories/{repository_id}
      Aggregate analytics for one repository (SRS FR-9.2).
      The caller must have active (non-revoked) RepositoryAccess.

Security:
  - Both endpoints require a valid X-Session-Token (get_current_user).
  - /repositories/{id}: authorization verified before any analytics data
    is fetched. If the user has no active RepositoryAccess row for the
    given repository_id, 404 is returned (same IDOR-safe convention used
    by the feedback endpoint: we do not confirm whether the resource
    exists to unauthorized callers).
  - Cross-user data leakage is impossible because:
    * /me always derives the user from the validated session.
    * /repositories/{id} scopes repository_access to the session user.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import RepositoryAnalyticsResponse, UserAnalyticsResponse
from app.analytics.service import get_repository_analytics, get_user_analytics
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import RepositoryNotFoundError
from app.core.models import RepositoryAccess, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ── GET /api/analytics/me ──────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserAnalyticsResponse,
    summary="Get analytics for the authenticated user",
    description=(
        "Returns aggregate analytics for the currently authenticated user, "
        "covering all repositories the user has active authorization for. "
        "The user is always derived from the session — the client cannot "
        "request analytics for another user."
    ),
)
async def user_analytics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserAnalyticsResponse:
    logger.info("User analytics requested by user_id=%s", current_user.id)
    return await get_user_analytics(db=db, user=current_user)


# ── GET /api/analytics/repositories/{repository_id} ───────────────────────────


@router.get(
    "/repositories/{repository_id}",
    response_model=RepositoryAnalyticsResponse,
    summary="Get analytics for a repository",
    description=(
        "Returns team-wide aggregate analytics for a single repository. "
        "The authenticated user must have active authorization for the "
        "repository. Unauthorized access returns 404 (IDOR-safe — same "
        "convention as the feedback endpoint)."
    ),
)
async def repository_analytics(
    repository_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RepositoryAnalyticsResponse:
    logger.info(
        "Repository analytics requested by user_id=%s for repo_id=%s",
        current_user.id,
        repository_id,
    )

    # ── Authorization check ────────────────────────────────────────────────────
    # Pattern mirrors the feedback service: 404 (not 403) so we don't leak
    # whether the repository exists at all to unauthorized callers.
    access_result = await db.execute(
        select(RepositoryAccess).where(
            RepositoryAccess.user_id == current_user.id,
            RepositoryAccess.repository_id == repository_id,
            RepositoryAccess.revoked_at.is_(None),
        )
    )
    access_row = access_result.scalar_one_or_none()

    if access_row is None:
        logger.warning(
            "Unauthorized repo analytics attempt: user_id=%s repo_id=%s",
            current_user.id,
            repository_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "repository_not_found",
                "message": "Repository not found or not authorized.",
            },
        )

    # ── Delegate to service ───────────────────────────────────────────────────
    try:
        return await get_repository_analytics(db=db, repository_id=repository_id)
    except RepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": exc.error_code, "message": exc.message},
        ) from exc
