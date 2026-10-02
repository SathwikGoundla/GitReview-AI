from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.checklist.schemas import ChecklistCompletionResponse
from app.core.exceptions import (
    DatabaseError,
    RepositoryNotFoundError,
    ValidationError,
)
from app.core.models import (
    ChecklistItem,
    ChecklistItemCompletion,
    PullRequest,
    PullRequestAnalysis,
    Repository,
    RepositoryAccess,
    User,
)

logger = logging.getLogger(__name__)


async def _get_authorized_analysis(
    db: AsyncSession,
    user: User,
    analysis_id: uuid.UUID,
) -> PullRequestAnalysis:
    stmt = (
        select(PullRequestAnalysis)
        .join(PullRequest, PullRequest.id == PullRequestAnalysis.pull_request_id)
        .join(Repository, Repository.id == PullRequest.repository_id)
        .join(
            RepositoryAccess,
            (RepositoryAccess.repository_id == Repository.id)
            & (RepositoryAccess.user_id == user.id)
            & (RepositoryAccess.revoked_at.is_(None)),
        )
        .where(PullRequestAnalysis.id == analysis_id)
    )

    result = await db.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise RepositoryNotFoundError(
            f"Analysis {analysis_id} not found or not authorized for the current user.",
            detail="Either the analysis does not exist, or you do not have access to the repository it belongs to.",
        )

    return analysis


async def _validate_checklist_item(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    item_id: uuid.UUID,
) -> ChecklistItem:
    stmt = select(ChecklistItem).where(
        ChecklistItem.id == item_id,
        ChecklistItem.analysis_id == analysis_id,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        raise ValidationError(
            "item_id does not match a checklist item for this analysis.",
            detail=f"No checklist_items row with id={item_id} belongs to analysis {analysis_id}.",
        )
    return item


async def update_checklist_completion(
    db: AsyncSession,
    user: User,
    analysis_id: uuid.UUID,
    item_id: uuid.UUID,
    completed: bool,
) -> ChecklistCompletionResponse:
    # 1. Authorize analysis
    analysis = await _get_authorized_analysis(db, user, analysis_id)

    # 2. Validate checklist item belongs to analysis
    item = await _validate_checklist_item(db, analysis.id, item_id)

    # 3. Handle completion state
    stmt = select(ChecklistItemCompletion).where(
        ChecklistItemCompletion.user_id == user.id,
        ChecklistItemCompletion.checklist_item_id == item.id,
    )
    result = await db.execute(stmt)
    completion = result.scalar_one_or_none()

    try:
        if completed:
            if not completion:
                completion = ChecklistItemCompletion(
                    checklist_item_id=item.id,
                    user_id=user.id,
                )
                db.add(completion)
        else:
            if completion:
                await db.delete(completion)

        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.error("Checklist completion integrity error: %s", exc)
        raise DatabaseError(
            "Failed to save checklist completion due to a database constraint violation.",
            detail=str(exc),
        ) from exc

    return ChecklistCompletionResponse(
        item_id=str(item.id),
        completed=completed,
    )
