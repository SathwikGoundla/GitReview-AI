"""
GitReview AI — Analytics Service (LLD A.18 / B.7 AnalyticsService)

Two public functions:
  get_user_analytics(db, user)            → UserAnalyticsResponse
  get_repository_analytics(db, repo_id)  → RepositoryAnalyticsResponse

Design notes:
  - All aggregation is performed in SQL (COUNT, GROUP BY, AVG) — never load
    full result sets into Python just to count rows.
  - user_daily_metrics / repository_daily_metrics exist in the schema but are
    populated by a nightly job (not implemented in MVP). We therefore compute
    analytics on demand from the transactional tables, which is correct and
    accurate for MVP scale (HLD Section 15 / LLD Part E: "derived, not
    authoritative — can always be recomputed from source data").
  - No new migrations. No Redis. No Celery. No new tables.
  - Authorization is enforced in the router before these functions are called.
    These functions only aggregate — they do not re-check authorization.

Tables actually used:
  repository_access, repositories, pull_requests,
  pull_request_analyses, risk_assessments,
  reviewer_recommendations, feedback
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import (
    FeedbackSummary,
    RepositoryAnalyticsResponse,
    ReviewerRecommendationSummary,
    RiskDistribution,
    UserAnalyticsResponse,
)
from app.core.models import (
    Feedback,
    PullRequest,
    PullRequestAnalysis,
    Repository,
    RepositoryAccess,
    ReviewerRecommendation,
    RiskAssessment,
    User,
)

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _risk_distribution_from_rows(rows: list) -> RiskDistribution:
    """Convert GROUP BY risk_tier result rows to RiskDistribution."""
    mapping: dict[str, int] = {}
    for row in rows:
        tier = row[0]
        count = int(row[1])
        if tier in ("low", "medium", "high", "critical"):
            mapping[tier] = count
    return RiskDistribution(
        low=mapping.get("low", 0),
        medium=mapping.get("medium", 0),
        high=mapping.get("high", 0),
        critical=mapping.get("critical", 0),
    )


def _feedback_summary(helpful: int, unhelpful: int) -> FeedbackSummary:
    total = helpful + unhelpful
    pct: float | None = None
    if total > 0:
        pct = round(helpful / total * 100, 1)
    return FeedbackSummary(total=total, helpful=helpful, unhelpful=unhelpful, helpful_pct=pct)


# ── User Analytics ─────────────────────────────────────────────────────────────


async def get_user_analytics(db: AsyncSession, user: User) -> UserAnalyticsResponse:
    """
    Compute aggregate analytics for one authenticated user.

    Scope: all analyses on pull requests in repositories the user has
    active (non-revoked) authorization for.

    This is the "individual contributor" analytics grain (SRS FR-9.1).
    """
    user_id = user.id

    # ── 1. Active authorized repository count ──────────────────────────────────
    auth_repo_count_result = await db.execute(
        select(func.count(RepositoryAccess.id)).where(
            RepositoryAccess.user_id == user_id,
            RepositoryAccess.revoked_at.is_(None),
        )
    )
    authorized_repo_count: int = auth_repo_count_result.scalar_one() or 0

    # ── 2. Pull request IDs inside user's authorized repos ────────────────────
    # Subquery: repo IDs the user currently has access to
    active_repo_ids_sq = (
        select(RepositoryAccess.repository_id)
        .where(
            RepositoryAccess.user_id == user_id,
            RepositoryAccess.revoked_at.is_(None),
        )
        .scalar_subquery()
    )

    # Subquery: PR IDs in those repos
    pr_ids_sq = (
        select(PullRequest.id)
        .where(PullRequest.repository_id.in_(active_repo_ids_sq))
        .scalar_subquery()
    )

    # ── 3. Analysis status counts ─────────────────────────────────────────────
    status_rows = (
        await db.execute(
            select(PullRequestAnalysis.status, func.count(PullRequestAnalysis.id).label("cnt"))
            .where(PullRequestAnalysis.pull_request_id.in_(pr_ids_sq))
            .group_by(PullRequestAnalysis.status)
        )
    ).all()

    status_map: dict[str, int] = {row[0]: int(row[1]) for row in status_rows}
    total_analyses = sum(status_map.values())
    completed = status_map.get("completed", 0)
    degraded = status_map.get("degraded", 0)
    failed = status_map.get("failed", 0)

    # ── 4. Unique PRs with at least one analysis ──────────────────────────────
    unique_prs_result = await db.execute(
        select(func.count(func.distinct(PullRequestAnalysis.pull_request_id))).where(
            PullRequestAnalysis.pull_request_id.in_(pr_ids_sq)
        )
    )
    unique_prs: int = unique_prs_result.scalar_one() or 0

    # ── 5. Timestamps (first / latest analysis) ───────────────────────────────
    ts_result = await db.execute(
        select(
            func.min(PullRequestAnalysis.created_at),
            func.max(PullRequestAnalysis.created_at),
        ).where(PullRequestAnalysis.pull_request_id.in_(pr_ids_sq))
    )
    ts_row = ts_result.one()
    first_at = ts_row[0]
    latest_at = ts_row[1]

    # ── 6. Completed analysis IDs (for risk / reviewer sub-queries) ───────────
    completed_ids_sq = (
        select(PullRequestAnalysis.id)
        .where(
            PullRequestAnalysis.pull_request_id.in_(pr_ids_sq),
            PullRequestAnalysis.status == "completed",
        )
        .scalar_subquery()
    )

    # ── 7. Risk distribution across completed analyses ─────────────────────────
    risk_rows = (
        await db.execute(
            select(RiskAssessment.risk_tier, func.count(RiskAssessment.id).label("cnt"))
            .where(RiskAssessment.analysis_id.in_(completed_ids_sq))
            .group_by(RiskAssessment.risk_tier)
        )
    ).all()
    risk_dist = _risk_distribution_from_rows(risk_rows)

    # ── 8. Average confidence score ───────────────────────────────────────────
    avg_conf_result = await db.execute(
        select(func.avg(RiskAssessment.confidence_score)).where(
            RiskAssessment.analysis_id.in_(completed_ids_sq)
        )
    )
    avg_conf_raw = avg_conf_result.scalar_one()
    avg_confidence: float | None = round(float(avg_conf_raw), 1) if avg_conf_raw is not None else None

    # ── 9. Reviewer recommendation stats ──────────────────────────────────────
    # Count how many completed analyses have a rank=1 recommendation row
    rec_made_result = await db.execute(
        select(func.count(ReviewerRecommendation.id)).where(
            ReviewerRecommendation.analysis_id.in_(completed_ids_sq),
            ReviewerRecommendation.rank == 1,
        )
    )
    recs_made: int = rec_made_result.scalar_one() or 0
    abstentions = completed - recs_made  # completed analyses minus those that got a rec

    # ── 10. Feedback this USER has given (feedback.user_id = this user) ───────
    fb_rows = (
        await db.execute(
            select(Feedback.rating, func.count(Feedback.id).label("cnt"))
            .where(Feedback.user_id == user_id)
            .group_by(Feedback.rating)
        )
    ).all()
    fb_map: dict[str, int] = {row[0]: int(row[1]) for row in fb_rows}
    feedback_given = _feedback_summary(
        helpful=fb_map.get("helpful", 0),
        unhelpful=fb_map.get("unhelpful", 0),
    )

    return UserAnalyticsResponse(
        user_id=str(user_id),
        github_username=user.github_username,
        total_analyses=total_analyses,
        completed_analyses=completed,
        degraded_analyses=degraded,
        failed_analyses=failed,
        unique_prs_analyzed=unique_prs,
        risk_distribution=risk_dist,
        avg_confidence=avg_confidence,
        feedback_given=feedback_given,
        reviewer_stats=ReviewerRecommendationSummary(
            recommendations_made=recs_made,
            abstentions=max(abstentions, 0),
        ),
        authorized_repository_count=authorized_repo_count,
        first_analysis_at=first_at,
        latest_analysis_at=latest_at,
    )


# ── Repository Analytics ───────────────────────────────────────────────────────


async def get_repository_analytics(
    db: AsyncSession,
    repository_id: uuid.UUID,
) -> RepositoryAnalyticsResponse:
    """
    Compute aggregate analytics for one repository (team-wide view, SRS FR-9.2).

    Authorization is verified in the router before this function is called.
    This function only aggregates data — it does not re-check authorization.
    """
    # ── 1. Repository identity ─────────────────────────────────────────────────
    repo_result = await db.execute(
        select(Repository).where(Repository.id == repository_id)
    )
    repo = repo_result.scalar_one_or_none()
    if repo is None:
        from app.core.exceptions import RepositoryNotFoundError
        raise RepositoryNotFoundError(
            f"Repository {repository_id} not found.",
            detail=f"repository_id={repository_id}",
        )

    # ── 2. Authorized user count ───────────────────────────────────────────────
    auth_users_result = await db.execute(
        select(func.count(RepositoryAccess.id)).where(
            RepositoryAccess.repository_id == repository_id,
            RepositoryAccess.revoked_at.is_(None),
        )
    )
    authorized_user_count: int = auth_users_result.scalar_one() or 0

    # ── 3. PR IDs for this repository ─────────────────────────────────────────
    pr_ids_sq = (
        select(PullRequest.id)
        .where(PullRequest.repository_id == repository_id)
        .scalar_subquery()
    )

    # ── 4. Analysis status counts ─────────────────────────────────────────────
    status_rows = (
        await db.execute(
            select(PullRequestAnalysis.status, func.count(PullRequestAnalysis.id).label("cnt"))
            .where(PullRequestAnalysis.pull_request_id.in_(pr_ids_sq))
            .group_by(PullRequestAnalysis.status)
        )
    ).all()

    status_map: dict[str, int] = {row[0]: int(row[1]) for row in status_rows}
    total_analyses = sum(status_map.values())
    completed = status_map.get("completed", 0)
    degraded = status_map.get("degraded", 0)
    failed = status_map.get("failed", 0)

    # ── 5. Unique PRs ──────────────────────────────────────────────────────────
    unique_prs_result = await db.execute(
        select(func.count(func.distinct(PullRequestAnalysis.pull_request_id))).where(
            PullRequestAnalysis.pull_request_id.in_(pr_ids_sq)
        )
    )
    unique_prs: int = unique_prs_result.scalar_one() or 0

    # ── 6. Timestamps ──────────────────────────────────────────────────────────
    ts_result = await db.execute(
        select(
            func.min(PullRequestAnalysis.created_at),
            func.max(PullRequestAnalysis.created_at),
        ).where(PullRequestAnalysis.pull_request_id.in_(pr_ids_sq))
    )
    ts_row = ts_result.one()

    # ── 7. Completed analysis IDs ─────────────────────────────────────────────
    completed_ids_sq = (
        select(PullRequestAnalysis.id)
        .where(
            PullRequestAnalysis.pull_request_id.in_(pr_ids_sq),
            PullRequestAnalysis.status == "completed",
        )
        .scalar_subquery()
    )

    # ── 8. Risk distribution ───────────────────────────────────────────────────
    risk_rows = (
        await db.execute(
            select(RiskAssessment.risk_tier, func.count(RiskAssessment.id).label("cnt"))
            .where(RiskAssessment.analysis_id.in_(completed_ids_sq))
            .group_by(RiskAssessment.risk_tier)
        )
    ).all()
    risk_dist = _risk_distribution_from_rows(risk_rows)

    # ── 9. Average confidence ──────────────────────────────────────────────────
    avg_conf_result = await db.execute(
        select(func.avg(RiskAssessment.confidence_score)).where(
            RiskAssessment.analysis_id.in_(completed_ids_sq)
        )
    )
    avg_conf_raw = avg_conf_result.scalar_one()
    avg_confidence: float | None = round(float(avg_conf_raw), 1) if avg_conf_raw is not None else None

    # ── 10. Reviewer stats ────────────────────────────────────────────────────
    rec_made_result = await db.execute(
        select(func.count(ReviewerRecommendation.id)).where(
            ReviewerRecommendation.analysis_id.in_(completed_ids_sq),
            ReviewerRecommendation.rank == 1,
        )
    )
    recs_made: int = rec_made_result.scalar_one() or 0

    # ── 11. Feedback on this repo's analyses ──────────────────────────────────
    # All analyses (not just completed) can receive feedback
    all_analysis_ids_sq = (
        select(PullRequestAnalysis.id)
        .where(PullRequestAnalysis.pull_request_id.in_(pr_ids_sq))
        .scalar_subquery()
    )
    fb_rows = (
        await db.execute(
            select(Feedback.rating, func.count(Feedback.id).label("cnt"))
            .where(Feedback.analysis_id.in_(all_analysis_ids_sq))
            .group_by(Feedback.rating)
        )
    ).all()
    fb_map: dict[str, int] = {row[0]: int(row[1]) for row in fb_rows}
    feedback_received = _feedback_summary(
        helpful=fb_map.get("helpful", 0),
        unhelpful=fb_map.get("unhelpful", 0),
    )

    return RepositoryAnalyticsResponse(
        repository_id=str(repository_id),
        github_repo_id=repo.github_repo_id,
        owner=repo.owner,
        name=repo.name,
        full_name=f"{repo.owner}/{repo.name}",
        total_analyses=total_analyses,
        completed_analyses=completed,
        degraded_analyses=degraded,
        failed_analyses=failed,
        unique_prs_analyzed=unique_prs,
        risk_distribution=risk_dist,
        avg_confidence=avg_confidence,
        feedback_received=feedback_received,
        reviewer_stats=ReviewerRecommendationSummary(
            recommendations_made=recs_made,
            abstentions=max(completed - recs_made, 0),
        ),
        authorized_user_count=authorized_user_count,
        first_analysis_at=ts_row[0],
        latest_analysis_at=ts_row[1],
    )
