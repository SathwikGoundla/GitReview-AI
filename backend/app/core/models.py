"""
GitReview AI — SQLAlchemy ORM Models

17 tables exactly as specified in the Database Validation & ER Design document.
Six corrections from the LLD draft are applied here:
  1. review_checklists removed; checklist_is_fallback_default moved to pull_request_analyses
  2. notifications deduplication via partial UNIQUE index (WHERE read_at IS NULL)
  3. feedback uses exclusive-arc FK (risk_assessment_id / reviewer_recommendation_id /
     checklist_item_id) + CHECK constraint instead of untyped prediction_reference_id
  4. analytics_daily_metrics split into user_daily_metrics + repository_daily_metrics
     (both fully NOT NULL)
  5. repository_access.role → github_permission_level with CHECK constraint
  6. Missing (pull_request_id, created_at DESC) index on pull_request_analyses added

All timestamps use DateTime(timezone=True).
UUIDs are server-generated (server_default=text("gen_random_uuid()")).
commit_sha fields use CHAR(40).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── 1. users ──────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    github_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    github_username: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_users_github_user_id", "github_user_id", unique=True),
        Index("ix_users_github_username", "github_username"),
    )

    sessions: Mapped[list[Session]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    repository_accesses: Mapped[list[RepositoryAccess]] = relationship(
        "RepositoryAccess", back_populates="user", cascade="all, delete-orphan"
    )
    checklist_completions: Mapped[list[ChecklistItemCompletion]] = relationship(
        "ChecklistItemCompletion", back_populates="user", cascade="all, delete-orphan"
    )
    feedbacks: Mapped[list[Feedback]] = relationship(
        "Feedback", back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
    user_daily_metrics: Mapped[list[UserDailyMetrics]] = relationship(
        "UserDailyMetrics", back_populates="user", cascade="all, delete-orphan"
    )


# ── 2. sessions ───────────────────────────────────────────────────────────────


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
        Index("ix_sessions_token_hash", "session_token_hash", unique=True),
    )

    user: Mapped[User] = relationship("User", back_populates="sessions")


# ── 3. repositories ───────────────────────────────────────────────────────────


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    github_repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_repositories_github_repo_id", "github_repo_id", unique=True),
        Index("ix_repositories_owner_name", "owner", "name", unique=True),
    )

    repository_accesses: Mapped[list[RepositoryAccess]] = relationship(
        "RepositoryAccess", back_populates="repository", cascade="all, delete-orphan"
    )
    pull_requests: Mapped[list[PullRequest]] = relationship(
        "PullRequest", back_populates="repository", cascade="all, delete-orphan"
    )
    repository_daily_metrics: Mapped[list[RepositoryDailyMetrics]] = relationship(
        "RepositoryDailyMetrics", back_populates="repository", cascade="all, delete-orphan"
    )


# ── 4. repository_access ──────────────────────────────────────────────────────


class RepositoryAccess(Base):
    """
    Many-to-many join implementing multi-repository authorization.
    DB Validation Correction #5: role replaced with github_permission_level
    (CHECK-constrained enum sourced from GitHub's collaborator-permission API).
    """

    __tablename__ = "repository_access"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    github_permission_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    authorized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "github_permission_level IN ('admin','maintain','write','read')",
            name="ck_repository_access_permission_level",
        ),
        UniqueConstraint("user_id", "repository_id", name="uq_repository_access_user_repo"),
        Index(
            "ix_repository_access_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    user: Mapped[User] = relationship("User", back_populates="repository_accesses")
    repository: Mapped[Repository] = relationship(
        "Repository", back_populates="repository_accesses"
    )


# ── 5. pull_requests ──────────────────────────────────────────────────────────


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    github_pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author_github_username: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    # CHAR(40): always the full 40-char SHA — never abbreviated
    latest_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('open','closed','merged')",
            name="ck_pull_requests_state",
        ),
        CheckConstraint(
            "char_length(latest_commit_sha) = 40",
            name="ck_pull_requests_sha_length",
        ),
        UniqueConstraint("repository_id", "github_pr_number", name="uq_pull_requests_repo_number"),
        Index("ix_pull_requests_repo_number", "repository_id", "github_pr_number", unique=True),
    )

    repository: Mapped[Repository] = relationship("Repository", back_populates="pull_requests")
    analyses: Mapped[list[PullRequestAnalysis]] = relationship(
        "PullRequestAnalysis", back_populates="pull_request", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification", back_populates="pull_request", cascade="all, delete-orphan"
    )


# ── 6. pull_request_analyses ──────────────────────────────────────────────────


class PullRequestAnalysis(Base):
    """
    Central per-analysis-run record and commit-SHA cache lookup table.
    DB Validation Correction #1: checklist_is_fallback_default added here
    (moved from removed review_checklists table).
    DB Validation Correction #6: (pull_request_id, created_at DESC) index added.
    """

    __tablename__ = "pull_request_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Correction #1: was review_checklists.is_fallback_default
    checklist_is_fallback_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    prompt_template_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('completed','degraded','failed')",
            name="ck_analyses_status",
        ),
        CheckConstraint(
            "triggered_by IN ('extension','github_action')",
            name="ck_analyses_triggered_by",
        ),
        CheckConstraint(
            "char_length(commit_sha) = 40",
            name="ck_analyses_sha_length",
        ),
        # Cache key (hottest query in the system)
        UniqueConstraint("pull_request_id", "commit_sha", name="uq_analyses_pr_sha"),
        # Correction #6: serves "get latest analysis for this PR"
        Index("ix_analyses_pr_created", "pull_request_id", "created_at"),
        Index("ix_analyses_created_at", "created_at"),
    )

    pull_request: Mapped[PullRequest] = relationship("PullRequest", back_populates="analyses")
    risk_assessment: Mapped[RiskAssessment | None] = relationship(
        "RiskAssessment", back_populates="analysis", uselist=False, cascade="all, delete-orphan"
    )
    review_suggestions: Mapped[list[ReviewSuggestion]] = relationship(
        "ReviewSuggestion", back_populates="analysis", cascade="all, delete-orphan"
    )
    reviewer_recommendations: Mapped[list[ReviewerRecommendation]] = relationship(
        "ReviewerRecommendation", back_populates="analysis", cascade="all, delete-orphan"
    )
    checklist_items: Mapped[list[ChecklistItem]] = relationship(
        "ChecklistItem", back_populates="analysis", cascade="all, delete-orphan"
    )
    feedbacks: Mapped[list[Feedback]] = relationship(
        "Feedback", back_populates="analysis", cascade="all, delete-orphan"
    )
    metrics_logs: Mapped[list[AnalysisMetricsLog]] = relationship(
        "AnalysisMetricsLog", back_populates="analysis"
    )


# ── 7. risk_assessments ───────────────────────────────────────────────────────


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_analyses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    risk_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    deterministic_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    ai_risk_signal: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "risk_tier IN ('low','medium','high','critical')",
            name="ck_risk_tier",
        ),
        CheckConstraint(
            "source IN ('deterministic_only','hybrid')",
            name="ck_risk_source",
        ),
        CheckConstraint(
            "confidence_score BETWEEN 0 AND 100",
            name="ck_risk_confidence_range",
        ),
        Index("ix_risk_assessments_analysis_id", "analysis_id", unique=True),
        Index("ix_risk_assessments_risk_tier", "risk_tier"),
    )

    analysis: Mapped[PullRequestAnalysis] = relationship(
        "PullRequestAnalysis", back_populates="risk_assessment"
    )
    feedbacks: Mapped[list[Feedback]] = relationship("Feedback", back_populates="risk_assessment")


# ── 8. review_suggestions ─────────────────────────────────────────────────────


class ReviewSuggestion(Base):
    __tablename__ = "review_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    focus_area: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (Index("ix_review_suggestions_analysis_id", "analysis_id"),)

    analysis: Mapped[PullRequestAnalysis] = relationship(
        "PullRequestAnalysis", back_populates="review_suggestions"
    )


# ── 9. reviewer_recommendations ───────────────────────────────────────────────


class ReviewerRecommendation(Base):
    """
    No row written when the Reviewer Recommendation Module abstains.
    DB Validation: UNIQUE(analysis_id, rank) prevents two rank=1 rows.
    """

    __tablename__ = "reviewer_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommended_github_username: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    confidence_score: Mapped[float] = mapped_column(Numeric, nullable=False)

    __table_args__ = (
        CheckConstraint("rank >= 1", name="ck_reviewer_rank_positive"),
        CheckConstraint(
            "confidence_score BETWEEN 0 AND 100",
            name="ck_reviewer_confidence_range",
        ),
        UniqueConstraint("analysis_id", "rank", name="uq_reviewer_analysis_rank"),
        Index("ix_reviewer_recommendations_analysis_rank", "analysis_id", "rank", unique=True),
    )

    analysis: Mapped[PullRequestAnalysis] = relationship(
        "PullRequestAnalysis", back_populates="reviewer_recommendations"
    )
    feedbacks: Mapped[list[Feedback]] = relationship(
        "Feedback", back_populates="reviewer_recommendation"
    )


# ── 10. checklist_items ───────────────────────────────────────────────────────


class ChecklistItem(Base):
    """
    DB Validation Correction #1: references pull_request_analyses.id directly
    (review_checklists table removed).
    DB Validation: UNIQUE(analysis_id, category) prevents duplicate categories.
    """

    __tablename__ = "checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "category IN ('security','performance','exception_handling','null_handling',"
            "'logging','testing','documentation','dependencies','database_changes')",
            name="ck_checklist_category",
        ),
        CheckConstraint(
            "trigger_source IN ('deterministic','ai','both')",
            name="ck_checklist_trigger_source",
        ),
        CheckConstraint(
            "confidence_score BETWEEN 0 AND 100",
            name="ck_checklist_confidence_range",
        ),
        UniqueConstraint("analysis_id", "category", name="uq_checklist_analysis_category"),
        Index("ix_checklist_items_analysis_id", "analysis_id"),
    )

    analysis: Mapped[PullRequestAnalysis] = relationship(
        "PullRequestAnalysis", back_populates="checklist_items"
    )
    completions: Mapped[list[ChecklistItemCompletion]] = relationship(
        "ChecklistItemCompletion", back_populates="checklist_item", cascade="all, delete-orphan"
    )
    feedbacks: Mapped[list[Feedback]] = relationship("Feedback", back_populates="checklist_item")


# ── 11. checklist_item_completions ────────────────────────────────────────────


class ChecklistItemCompletion(Base):
    """
    Per-reviewer completion tracking. Presence = complete; absence = incomplete.
    No 'state' column — two-value model cannot be invalid.
    """

    __tablename__ = "checklist_item_completions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    checklist_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("checklist_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("checklist_item_id", "user_id", name="uq_completion_item_user"),
        Index("ix_completion_user_id", "user_id"),
    )

    checklist_item: Mapped[ChecklistItem] = relationship(
        "ChecklistItem", back_populates="completions"
    )
    user: Mapped[User] = relationship("User", back_populates="checklist_completions")


# ── 12. feedback ──────────────────────────────────────────────────────────────


class Feedback(Base):
    """
    DB Validation Correction #3: exclusive-arc FKs replace untyped
    prediction_reference_id. CHECK constraint enforces exactly one is set
    and it matches prediction_type.
    """

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    prediction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Exclusive-arc FKs (exactly one must be non-null, enforced by CHECK below)
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("risk_assessments.id", ondelete="CASCADE"),
        nullable=True,
    )
    reviewer_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviewer_recommendations.id", ondelete="CASCADE"),
        nullable=True,
    )
    checklist_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("checklist_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "prediction_type IN ('risk_tier','reviewer_recommendation','checklist_item')",
            name="ck_feedback_prediction_type",
        ),
        CheckConstraint(
            "rating IN ('helpful','unhelpful')",
            name="ck_feedback_rating",
        ),
        # Exclusive-arc: exactly one FK non-null, matching prediction_type
        CheckConstraint(
            """
            (prediction_type = 'risk_tier'
                AND risk_assessment_id IS NOT NULL
                AND reviewer_recommendation_id IS NULL
                AND checklist_item_id IS NULL)
            OR
            (prediction_type = 'reviewer_recommendation'
                AND reviewer_recommendation_id IS NOT NULL
                AND risk_assessment_id IS NULL
                AND checklist_item_id IS NULL)
            OR
            (prediction_type = 'checklist_item'
                AND checklist_item_id IS NOT NULL
                AND risk_assessment_id IS NULL
                AND reviewer_recommendation_id IS NULL)
            """,
            name="ck_feedback_exclusive_arc",
        ),
        # One rating per user per risk assessment
        Index(
            "ix_feedback_risk",
            "user_id",
            "risk_assessment_id",
            postgresql_where=text("risk_assessment_id IS NOT NULL"),
            unique=True,
        ),
        # One rating per user per reviewer recommendation
        Index(
            "ix_feedback_reviewer",
            "user_id",
            "reviewer_recommendation_id",
            postgresql_where=text("reviewer_recommendation_id IS NOT NULL"),
            unique=True,
        ),
        # One rating per user per checklist item
        Index(
            "ix_feedback_checklist",
            "user_id",
            "checklist_item_id",
            postgresql_where=text("checklist_item_id IS NOT NULL"),
            unique=True,
        ),
        Index("ix_feedback_prediction_type", "prediction_type"),
        Index("ix_feedback_analysis_id", "analysis_id"),
    )

    user: Mapped[User] = relationship("User", back_populates="feedbacks")
    analysis: Mapped[PullRequestAnalysis] = relationship(
        "PullRequestAnalysis", back_populates="feedbacks"
    )
    risk_assessment: Mapped[RiskAssessment | None] = relationship(
        "RiskAssessment", back_populates="feedbacks"
    )
    reviewer_recommendation: Mapped[ReviewerRecommendation | None] = relationship(
        "ReviewerRecommendation", back_populates="feedbacks"
    )
    checklist_item: Mapped[ChecklistItem | None] = relationship(
        "ChecklistItem", back_populates="feedbacks"
    )


# ── 13. notifications ─────────────────────────────────────────────────────────


class Notification(Base):
    """
    DB Validation Correction #2: deduplication is a PARTIAL UNIQUE index
    WHERE read_at IS NULL, not a permanent UNIQUE constraint.
    This allows re-alerting when a condition recurs after being read.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(40), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('high_risk_assigned','pr_stale')",
            name="ck_notification_type",
        ),
        # Correction #2: partial unique — prevents duplicate UNREAD alerts
        Index(
            "ix_notifications_unread_dedup",
            "user_id",
            "pull_request_id",
            "notification_type",
            postgresql_where=text("read_at IS NULL"),
            unique=True,
        ),
        # Unread badge count query
        Index(
            "ix_notifications_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        # Full notification history view
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    user: Mapped[User] = relationship("User", back_populates="notifications")
    pull_request: Mapped[PullRequest] = relationship("PullRequest", back_populates="notifications")


# ── 14. user_daily_metrics ────────────────────────────────────────────────────


class UserDailyMetrics(Base):
    """
    DB Validation Correction #4 (split from analytics_daily_metrics).
    Powers individual analytics (SRS FR-9.1). user_id is NOT NULL.
    """

    __tablename__ = "user_daily_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prs_reviewed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    avg_time_to_first_review_minutes: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    risk_tier_distribution: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )

    __table_args__ = (
        UniqueConstraint("user_id", "metric_date", name="uq_user_daily_metrics"),
        Index("ix_user_daily_metrics_date", "metric_date"),
    )

    user: Mapped[User] = relationship("User", back_populates="user_daily_metrics")


# ── 15. repository_daily_metrics ──────────────────────────────────────────────


class RepositoryDailyMetrics(Base):
    """
    DB Validation Correction #4 (split from analytics_daily_metrics).
    Powers team-lead analytics (SRS FR-9.2). repository_id is NOT NULL.
    """

    __tablename__ = "repository_daily_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prs_reviewed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    avg_time_to_first_review_minutes: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    risk_tier_distribution: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )

    __table_args__ = (
        UniqueConstraint("repository_id", "metric_date", name="uq_repo_daily_metrics"),
        Index("ix_repo_daily_metrics_date", "metric_date"),
    )

    repository: Mapped[Repository] = relationship(
        "Repository", back_populates="repository_daily_metrics"
    )


# ── 16. confidence_calibration ────────────────────────────────────────────────


class ConfidenceCalibration(Base):
    """
    Running helpful/unhelpful ratio per prediction_type.
    Exactly three rows will ever exist (one per type).
    Never scanned on the hot path — only the row for the queried type is read.
    """

    __tablename__ = "confidence_calibration"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    prediction_type: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    helpful_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    unhelpful_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "prediction_type IN ('risk_tier','reviewer_recommendation','checklist_item')",
            name="ck_calibration_prediction_type",
        ),
        Index("ix_confidence_calibration_type", "prediction_type", unique=True),
    )


# ── 17. analysis_metrics_log ──────────────────────────────────────────────────


class AnalysisMetricsLog(Base):
    """
    Append-only observability log. Uses ON DELETE SET NULL (not CASCADE)
    so metrics outlive archived analysis rows.
    """

    __tablename__ = "analysis_metrics_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # SET NULL — metrics intentionally outlive the analysis row
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('ai_latency','ai_failure','github_rate_limit',"
            "'analysis_success','analysis_failure')",
            name="ck_metrics_event_type",
        ),
        Index("ix_metrics_log_event_created", "event_type", "created_at"),
    )

    analysis: Mapped[PullRequestAnalysis | None] = relationship(
        "PullRequestAnalysis", back_populates="metrics_logs"
    )
