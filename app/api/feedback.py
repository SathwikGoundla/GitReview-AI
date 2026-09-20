"""
GitReview AI — Feedback API Router (LLD A.17)

Exposes the feedback submission endpoint:

  POST /api/analyses/{analysis_id}/feedback

Design notes:
  - Route is nested under /api/analyses/{analysis_id} because feedback is always
    scoped to a specific analysis. This makes the ownership hierarchy explicit in
    the URL and prevents callers from omitting the analysis scope.
  - Authentication is enforced via get_current_user (X-Session-Token header).
  - Authorization is enforced inside the service layer:
      analysis_id → pull_request → repository → repository_access(user_id)
    A 404 is returned (not 403) when an analysis is inaccessible to prevent
    resource enumeration (IDOR protection).
  - HTTP 200 is returned for both new feedback and upserted (updated) feedback,
    since the client observes the same result either way: the current rating is
    stored. HTTP 201 would imply only creation; upsert semantics makes 200 more
    accurate.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    DatabaseError,
    RepositoryNotFoundError,
    ValidationError,
)
from app.core.models import User
from app.feedback.schemas import FeedbackResponse, SubmitFeedbackRequest
from app.feedback.service import submit_feedback

router = APIRouter(prefix="/api/analyses", tags=["feedback"])


@router.post(
    "/{analysis_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit feedback on an AI prediction",
    description=(
        "Record a helpful/unhelpful rating for a specific AI prediction "
        "(risk tier, reviewer recommendation, or checklist item) within an analysis. "
        "The calling user must have active repository access for the repository "
        "that owns this analysis. "
        "Submitting feedback a second time for the same prediction updates the rating "
        "(upsert semantics)."
    ),
    responses={
        200: {"description": "Feedback recorded (new or updated)."},
        400: {"description": "Invalid prediction reference."},
        401: {"description": "Missing or invalid session token."},
        404: {"description": "Analysis not found or not authorized."},
        422: {"description": "Payload validation failed."},
    },
)
async def submit_analysis_feedback(
    analysis_id: uuid.UUID,
    body: SubmitFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """
    POST /api/analyses/{analysis_id}/feedback

    Submit or update feedback for one AI prediction within the given analysis.

    Path parameter:
      analysis_id — UUID of the pull_request_analyses row.

    Request body (SubmitFeedbackRequest):
      prediction_type        — "risk_tier" | "reviewer_recommendation" | "checklist_item"
      prediction_reference_id — UUID of the specific prediction row being rated
      rating                 — "helpful" | "unhelpful"
      comment                — optional free-text (max 2000 chars)

    Returns FeedbackResponse with the stored feedback_id and confirmation fields.

    Security:
      - Requires X-Session-Token header (401 if absent/invalid).
      - Verifies user has active RepositoryAccess for the analysis's repository (404 if not).
      - Verifies prediction_reference_id belongs to analysis_id (400 if not).
      - Never exposes whether an unauthorized analysis exists (IDOR prevention via 404).
    """
    try:
        return await submit_feedback(
            db=db,
            user=current_user,
            analysis_id=analysis_id,
            prediction_type=body.prediction_type,
            prediction_reference_id=body.prediction_reference_id,
            rating=body.rating,
            comment=body.comment,
        )
    except RepositoryNotFoundError:
        raise
    except ValidationError:
        raise
    except DatabaseError:
        raise
