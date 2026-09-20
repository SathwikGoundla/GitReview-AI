"""
GitReview AI — Feedback Service (LLD A.17 / B.7)

Captures and stores helpful/unhelpful feedback per individual prediction instance.

Design rules:
  - Feedback must reference a real prediction the user is authorized to access.
  - Authorization path: analysis → pull_request → repository → repository_access.
    The user must have an active (non-revoked) RepositoryAccess row for the
    repository that owns the PR that owns the analysis.
  - IDOR prevention: if the analysis_id is valid but the user is not authorized
    for that repository, we return RepositoryNotFoundError (404), not 403,
    to avoid leaking whether the analysis exists at all.
  - Duplicate semantics (per DB Validation doc and LLD A.17):
    "Duplicate feedback on the same prediction — upserted, not duplicated."
    The three partial UNIQUE indexes (one per prediction type) enforce one rating
    per user per prediction at the DB level. We handle the constraint violation
    by updating the existing row instead.
  - Calibration update (LLD A.17 / Part I): After persisting feedback, the
    confidence_calibration row for the matching prediction_type is updated
    immediately (increment helpful_count or unhelpful_count). This is the
    incremental calibration approach defined by the LLD. The calibration table
    has exactly 3 rows (one per type), seeded on DB creation.
  - No Celery, Redis, or background workers. In-process, synchronous update
    consistent with the approved MVP modular-monolith architecture.

LLD authoritative references:
  - A.17 Feedback Module: submit_feedback, get_calibration_aggregate
  - B.7 FeedbackService: submit_feedback(user_id, reference, rating)
  - Part I: "historical calibration from feedback" — helpful/unhelpful ratio
  - DB Validation Part 5 Feature Traceability: "updates confidence_calibration's
    running counts" on feedback submission.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DatabaseError,
    RepositoryNotFoundError,
    ValidationError,
)
from app.core.models import (
    ChecklistItem,
    ConfidenceCalibration,
    Feedback,
    PullRequest,
    PullRequestAnalysis,
    Repository,
    RepositoryAccess,
    ReviewerRecommendation,
    RiskAssessment,
    User,
)
from app.feedback.schemas import FeedbackRating, FeedbackResponse, PredictionType

logger = logging.getLogger(__name__)


# ── Authorization ─────────────────────────────────────────────────────────────


async def _get_authorized_analysis(
    db: AsyncSession,
    user: User,
    analysis_id: uuid.UUID,
) -> PullRequestAnalysis:
    """
    Resolve analysis_id to a PullRequestAnalysis, verifying the calling user is
    authorized for the repository that owns the PR that owns the analysis.

    Authorization path:
      pull_request_analyses → pull_requests → repositories → repository_access

    Returns the analysis ORM object if authorized.
    Raises RepositoryNotFoundError (404) if:
      - The analysis_id does not exist
      - The analysis exists but the user is not authorized (no IDOR leak)
    Raises PullRequestNotFoundError (404) if the PR row is missing (should not
      happen with ON DELETE CASCADE, but guarded defensively).
    """
    # Single query joining the entire ownership chain
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
        # Intentionally 404 (not 403) to prevent resource enumeration.
        # A 403 would confirm the analysis exists; a 404 reveals nothing.
        raise RepositoryNotFoundError(
            f"Analysis {analysis_id} not found or not authorized for the current user.",
            detail="Either the analysis does not exist, or you do not have access to the "
            "repository it belongs to.",
        )

    return analysis


# ── Prediction reference validation ───────────────────────────────────────────


async def _validate_prediction_reference(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    prediction_type: PredictionType,
    prediction_reference_id: uuid.UUID,
) -> tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    """
    Verify that prediction_reference_id points to a real row belonging to
    the given analysis_id, and return the exclusive-arc FK tuple.

    Returns a tuple (risk_assessment_id, reviewer_recommendation_id, checklist_item_id)
    with exactly one non-None value matching the prediction_type.

    Raises ValidationError if:
      - The reference ID does not exist for this analysis
      - The reference row belongs to a different analysis (IDOR between analyses)
    """
    risk_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID | None = None
    checklist_id: uuid.UUID | None = None

    if prediction_type == PredictionType.risk_tier:
        stmt = select(RiskAssessment).where(
            RiskAssessment.id == prediction_reference_id,
            RiskAssessment.analysis_id == analysis_id,
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValidationError(
                "prediction_reference_id does not match a risk assessment for this analysis.",
                detail=f"No risk_assessments row with id={prediction_reference_id} "
                f"belongs to analysis {analysis_id}.",
            )
        risk_id = prediction_reference_id

    elif prediction_type == PredictionType.reviewer_recommendation:
        stmt = select(ReviewerRecommendation).where(
            ReviewerRecommendation.id == prediction_reference_id,
            ReviewerRecommendation.analysis_id == analysis_id,
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValidationError(
                "prediction_reference_id does not match a reviewer recommendation "
                "for this analysis.",
                detail=f"No reviewer_recommendations row with id={prediction_reference_id} "
                f"belongs to analysis {analysis_id}.",
            )
        reviewer_id = prediction_reference_id

    elif prediction_type == PredictionType.checklist_item:
        stmt = select(ChecklistItem).where(
            ChecklistItem.id == prediction_reference_id,
            ChecklistItem.analysis_id == analysis_id,
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValidationError(
                "prediction_reference_id does not match a checklist item for this analysis.",
                detail=f"No checklist_items row with id={prediction_reference_id} "
                f"belongs to analysis {analysis_id}.",
            )
        checklist_id = prediction_reference_id

    return risk_id, reviewer_id, checklist_id


# ── Calibration update ────────────────────────────────────────────────────────


async def _update_calibration(
    db: AsyncSession,
    prediction_type: str,
    rating: FeedbackRating,
    is_new_record: bool,
    old_rating: str | None,
) -> None:
    """
    Increment (or adjust) the confidence_calibration running counts for
    this prediction_type.

    LLD Part I: "historical feedback calibration: the helpful/unhelpful ratio
    for this prediction_type from confidence_calibration, applied only once a
    minimum feedback sample size exists."

    DB Validation Part 5: "updates confidence_calibration's running counts"
    on feedback submission.

    If this is a NEW feedback record: simply increment the matching counter.
    If this is an UPDATE (upsert over existing): decrement old counter, increment new.
    This keeps the calibration counts accurate even when users change their rating.

    Note: confidence_calibration rows are seeded (3 rows, one per type).
    If a row is missing (cold start before seeding), this is a no-op with a warning.
    """
    stmt = select(ConfidenceCalibration).where(
        ConfidenceCalibration.prediction_type == prediction_type
    )
    result = await db.execute(stmt)
    calibration = result.scalar_one_or_none()

    if calibration is None:
        # Calibration not seeded yet — log and skip. Do not fail the feedback write.
        logger.warning(
            "confidence_calibration row missing for prediction_type=%s; "
            "calibration update skipped.",
            prediction_type,
        )
        return

    if not is_new_record and old_rating is not None:
        # User changed their rating — undo the old count first.
        if old_rating == FeedbackRating.helpful.value:
            calibration.helpful_count = max(0, calibration.helpful_count - 1)
        else:
            calibration.unhelpful_count = max(0, calibration.unhelpful_count - 1)

    # Increment the new rating counter.
    if rating == FeedbackRating.helpful:
        calibration.helpful_count += 1
    else:
        calibration.unhelpful_count += 1

    calibration.last_updated_at = datetime.now(UTC)
    db.add(calibration)


# ── Core feedback submission ───────────────────────────────────────────────────


async def submit_feedback(
    db: AsyncSession,
    user: User,
    analysis_id: uuid.UUID,
    prediction_type: PredictionType,
    prediction_reference_id: uuid.UUID,
    rating: FeedbackRating,
    comment: str | None,
) -> FeedbackResponse:
    """
    Submit or update feedback for a specific AI prediction.

    Steps:
      1. Verify the user is authorized for the analysis (via repository access chain).
      2. Verify prediction_reference_id belongs to this analysis.
      3. Check if a feedback record already exists (for upsert semantics).
      4. Create or update the feedback row.
      5. Update confidence_calibration counters.
      6. Commit.
      7. Return FeedbackResponse.

    Duplicate semantics (LLD A.17 + DB Validation):
      "upserted, not duplicated" — if the user has already rated this prediction,
      their rating is updated in place. The partial UNIQUE indexes enforce
      one row per (user, prediction-FK) combination.

    IDOR prevention:
      - analysis_id checked against user's authorized repositories.
      - prediction_reference_id checked against analysis_id.
      - Neither check leaks whether a resource exists to unauthorized callers.
    """
    # Step 1: Authorization
    analysis = await _get_authorized_analysis(db, user, analysis_id)

    # Step 2: Validate prediction reference
    risk_id, reviewer_id, checklist_id = await _validate_prediction_reference(
        db,
        analysis.id,
        prediction_type,
        prediction_reference_id,
    )

    # Step 3: Check for existing feedback (for upsert)
    existing_feedback: Feedback | None = None
    old_rating: str | None = None

    # Build the lookup filter based on prediction type
    if prediction_type == PredictionType.risk_tier:
        lookup_stmt = select(Feedback).where(
            Feedback.user_id == user.id,
            Feedback.risk_assessment_id == prediction_reference_id,
        )
    elif prediction_type == PredictionType.reviewer_recommendation:
        lookup_stmt = select(Feedback).where(
            Feedback.user_id == user.id,
            Feedback.reviewer_recommendation_id == prediction_reference_id,
        )
    else:  # checklist_item
        lookup_stmt = select(Feedback).where(
            Feedback.user_id == user.id,
            Feedback.checklist_item_id == prediction_reference_id,
        )

    result = await db.execute(lookup_stmt)
    existing_feedback = result.scalar_one_or_none()
    is_new_record = existing_feedback is None

    if existing_feedback is not None:
        # Upsert: update the existing record
        old_rating = existing_feedback.rating
        existing_feedback.rating = rating.value
        existing_feedback.comment = comment
        # created_at is immutable — only the rating/comment are updated
        feedback_record = existing_feedback
        db.add(feedback_record)
    else:
        # New feedback record
        feedback_record = Feedback(
            user_id=user.id,
            analysis_id=analysis.id,
            prediction_type=prediction_type.value,
            risk_assessment_id=risk_id,
            reviewer_recommendation_id=reviewer_id,
            checklist_item_id=checklist_id,
            rating=rating.value,
            comment=comment,
        )
        db.add(feedback_record)

    # Step 5: Update calibration counters
    await _update_calibration(
        db,
        prediction_type=prediction_type.value,
        rating=rating,
        is_new_record=is_new_record,
        old_rating=old_rating,
    )

    # Step 6: Commit
    try:
        await db.flush()  # Assign server-generated id if new
        await db.commit()
        await db.refresh(feedback_record)
    except IntegrityError as exc:
        await db.rollback()
        logger.error("Feedback integrity error: %s", exc)
        raise DatabaseError(
            "Failed to save feedback due to a database constraint violation.",
            detail=str(exc),
        ) from exc

    logger.info(
        "Feedback %s for analysis=%s prediction_type=%s by user=%s rating=%s",
        "updated" if not is_new_record else "created",
        analysis_id,
        prediction_type.value,
        user.id,
        rating.value,
    )

    return FeedbackResponse(
        feedback_id=feedback_record.id,
        analysis_id=analysis.id,
        prediction_type=prediction_type,
        prediction_reference_id=prediction_reference_id,
        rating=rating,
        created_at=feedback_record.created_at,
    )
