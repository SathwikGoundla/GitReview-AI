"""
GitReview AI — Analytics Pydantic Response Schemas (LLD A.18 / SRS FR-9)

Two response models:
  UserAnalyticsResponse       → GET /api/analytics/me
  RepositoryAnalyticsResponse → GET /api/analytics/repositories/{repository_id}

All fields derive from data that genuinely exists in the current schema.
No fabricated metrics, no fields that cannot be calculated from real tables.

Tables used:
  pull_request_analyses   — status counts, timestamps, triggered_by
  risk_assessments        — risk_tier, confidence_score
  reviewer_recommendations — rank (abstain detection), confidence_score
  feedback                — rating (helpful/unhelpful)
  repository_access       — authorized_repo_count, active user count
  pull_requests           — unique PR count
  repositories            — identity fields for repo response
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RiskDistribution(BaseModel):
    """Count of completed analyses per risk tier."""

    low: int = Field(0, ge=0)
    medium: int = Field(0, ge=0)
    high: int = Field(0, ge=0)
    critical: int = Field(0, ge=0)


class FeedbackSummary(BaseModel):
    """Aggregate helpful / unhelpful counts."""

    total: int = Field(0, ge=0)
    helpful: int = Field(0, ge=0)
    unhelpful: int = Field(0, ge=0)
    helpful_pct: float | None = Field(
        None,
        description="Percentage of helpful ratings. None when total == 0.",
    )


class ReviewerRecommendationSummary(BaseModel):
    """Summary of reviewer recommendation output across analyses."""

    recommendations_made: int = Field(
        0,
        ge=0,
        description="Analyses where a reviewer was recommended (rank=1 row exists).",
    )
    abstentions: int = Field(
        0,
        ge=0,
        description=(
            "Completed analyses where the module abstained "
            "(no reviewer_recommendations row written)."
        ),
    )


class UserAnalyticsResponse(BaseModel):
    """
    Aggregate analytics for the authenticated user.

    Covers all repositories the user currently has active authorization for.
    Counts reflect stored, validated analysis results only.
    """

    user_id: str
    github_username: str

    # Analysis counts
    total_analyses: int = Field(0, ge=0, description="All analyses on user's authorized repos")
    completed_analyses: int = Field(0, ge=0)
    degraded_analyses: int = Field(0, ge=0)
    failed_analyses: int = Field(0, ge=0)

    # Unique PRs
    unique_prs_analyzed: int = Field(
        0, ge=0, description="Distinct PRs with at least one analysis"
    )

    # Risk picture across completed analyses
    risk_distribution: RiskDistribution = Field(default_factory=RiskDistribution)

    # Average confidence (completed analyses only, null if none)
    avg_confidence: float | None = Field(
        None, description="Mean risk-assessment confidence score (0–100). None if no data."
    )

    # Feedback the user has submitted
    feedback_given: FeedbackSummary = Field(default_factory=FeedbackSummary)

    # Reviewer recommendation stats
    reviewer_stats: ReviewerRecommendationSummary = Field(
        default_factory=ReviewerRecommendationSummary
    )

    # Authorization scope
    authorized_repository_count: int = Field(
        0, ge=0, description="Active (non-revoked) repository authorizations"
    )

    # Activity window
    first_analysis_at: datetime | None = None
    latest_analysis_at: datetime | None = None

    model_config = {"from_attributes": True}


class RepositoryAnalyticsResponse(BaseModel):
    """
    Aggregate analytics for one repository (team-wide view, SRS FR-9.2).

    The requesting user must have active authorization.
    Data covers all users' analyses on this repository.
    """

    repository_id: str
    github_repo_id: int
    owner: str
    name: str
    full_name: str  # "{owner}/{name}"

    # Analysis counts (all users on this repo)
    total_analyses: int = Field(0, ge=0)
    completed_analyses: int = Field(0, ge=0)
    degraded_analyses: int = Field(0, ge=0)
    failed_analyses: int = Field(0, ge=0)

    # Unique PRs
    unique_prs_analyzed: int = Field(0, ge=0)

    # Risk distribution across completed analyses
    risk_distribution: RiskDistribution = Field(default_factory=RiskDistribution)

    # Average confidence (null if no completed analyses)
    avg_confidence: float | None = None

    # Feedback received across all predictions on this repo's analyses
    feedback_received: FeedbackSummary = Field(default_factory=FeedbackSummary)

    # Reviewer stats
    reviewer_stats: ReviewerRecommendationSummary = Field(
        default_factory=ReviewerRecommendationSummary
    )

    # Users with active authorization
    authorized_user_count: int = Field(0, ge=0)

    # Activity window
    first_analysis_at: datetime | None = None
    latest_analysis_at: datetime | None = None

    model_config = {"from_attributes": True}
