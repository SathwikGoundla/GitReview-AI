"""
GitReview AI — Feedback API Schemas (LLD A.17 / B.7)

Request/response Pydantic models for the feedback endpoint.

Design rules:
  - prediction_type and rating are constrained enums matching the DB CHECK constraints.
  - prediction_reference_id is the UUID of the specific prediction being rated:
      risk_tier         → risk_assessment_id (from analysis risk result)
      reviewer_recommendation → reviewer_recommendation_id
      checklist_item    → checklist_item_id
  - No internal credentials, raw tokens, or DB internals are exposed.
  - Optional comment field allows free-text context (nullable in DB).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class PredictionType(StrEnum):
    """Matches the DB CHECK constraint on feedback.prediction_type."""

    risk_tier = "risk_tier"
    reviewer_recommendation = "reviewer_recommendation"
    checklist_item = "checklist_item"


class FeedbackRating(StrEnum):
    """Matches the DB CHECK constraint on feedback.rating."""

    helpful = "helpful"
    unhelpful = "unhelpful"


class SubmitFeedbackRequest(BaseModel):
    """
    Request body for POST /api/analyses/{analysis_id}/feedback.

    prediction_type: which kind of prediction is being rated.
    prediction_reference_id: the UUID of the specific prediction row
      (risk_assessments.id, reviewer_recommendations.id, or checklist_items.id).
    rating: helpful | unhelpful
    comment: optional free-text context from the reviewer.
    """

    prediction_type: PredictionType = Field(
        ...,
        description="Which AI prediction is being rated.",
        examples=["risk_tier"],
    )
    prediction_reference_id: uuid.UUID = Field(
        ...,
        description=(
            "UUID of the specific prediction being rated. "
            "For risk_tier: risk_assessments.id. "
            "For reviewer_recommendation: reviewer_recommendations.id. "
            "For checklist_item: checklist_items.id."
        ),
    )
    rating: FeedbackRating = Field(
        ...,
        description="helpful or unhelpful.",
        examples=["helpful"],
    )
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional free-text context (stored but not currently surfaced in UI).",
    )

    @model_validator(mode="after")
    def comment_not_whitespace_only(self) -> SubmitFeedbackRequest:
        """Strip whitespace; treat whitespace-only as None."""
        if self.comment is not None:
            stripped = self.comment.strip()
            self.comment = stripped if stripped else None
        return self


class FeedbackResponse(BaseModel):
    """
    Response body for a successful feedback submission.

    Deliberately minimal: returns only the feedback id and core fields.
    Does not expose internal DB structure, other users' data, or credentials.
    """

    feedback_id: uuid.UUID = Field(..., description="UUID of the persisted feedback record.")
    analysis_id: uuid.UUID = Field(..., description="UUID of the analysis this feedback concerns.")
    prediction_type: PredictionType = Field(..., description="The rated prediction type.")
    prediction_reference_id: uuid.UUID = Field(
        ..., description="UUID of the rated prediction row."
    )
    rating: FeedbackRating = Field(..., description="The recorded rating.")
    created_at: datetime = Field(..., description="Timestamp when this feedback was persisted.")

    model_config = {"from_attributes": True}
