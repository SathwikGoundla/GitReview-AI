from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.checklist.schemas import ChecklistCompletionRequest, ChecklistCompletionResponse
from app.analysis.checklist.service import update_checklist_completion
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    DatabaseError,
    RepositoryNotFoundError,
    ValidationError,
)
from app.core.models import User

router = APIRouter(prefix="/api/analyses", tags=["checklist"])


@router.patch(
    "/{analysis_id}/checklist/{item_id}",
    response_model=ChecklistCompletionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update checklist item completion",
    description=(
        "Mark a checklist item as complete or incomplete. "
        "The calling user must have active repository access for the repository "
        "that owns this analysis."
    ),
    responses={
        200: {"description": "Checklist item completion updated."},
        400: {"description": "Invalid item reference."},
        401: {"description": "Missing or invalid session token."},
        404: {"description": "Analysis not found or not authorized."},
        422: {"description": "Payload validation failed."},
    },
)
async def update_analysis_checklist_item(
    analysis_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ChecklistCompletionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChecklistCompletionResponse:
    try:
        return await update_checklist_completion(
            db=db,
            user=current_user,
            analysis_id=analysis_id,
            item_id=item_id,
            completed=body.completed,
        )
    except RepositoryNotFoundError:
        raise
    except ValidationError:
        raise
    except DatabaseError:
        raise
