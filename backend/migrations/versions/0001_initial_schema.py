"""Initial schema — 17 tables (Database Validation doc v1.0)

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-18

All six DB Validation corrections are applied:
  1. review_checklists removed; checklist_is_fallback_default on pull_request_analyses
  2. notifications: partial UNIQUE index WHERE read_at IS NULL
  3. feedback: exclusive-arc FKs + CHECK constraint
  4. analytics split into user_daily_metrics + repository_daily_metrics
  5. repository_access: github_permission_level replaces role
  6. pull_request_analyses: (pull_request_id, created_at) index added
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("github_username", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "preferences", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_user_id"),
    )
    op.create_index("ix_users_github_user_id", "users", ["github_user_id"], unique=True)
    op.create_index("ix_users_github_username", "users", ["github_username"])

    # ── repositories ───────────────────────────────────────────────────────
    op.create_table(
        "repositories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_repo_id"),
    )
    op.create_index(
        "ix_repositories_github_repo_id", "repositories", ["github_repo_id"], unique=True
    )
    op.create_index("ix_repositories_owner_name", "repositories", ["owner", "name"], unique=True)

    # ── sessions ───────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_sessions_token_hash", "sessions", ["session_token_hash"], unique=True)

    # ── repository_access (Correction #5: github_permission_level) ─────────
    op.create_table(
        "repository_access",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_permission_level", sa.String(20), nullable=True),
        sa.Column(
            "authorized_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "github_permission_level IN ('admin','maintain','write','read')",
            name="ck_repository_access_permission_level",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "repository_id", name="uq_repository_access_user_repo"),
    )
    op.execute(
        "CREATE INDEX ix_repository_access_active ON repository_access (user_id) "
        "WHERE revoked_at IS NULL"
    )

    # ── pull_requests ──────────────────────────────────────────────────────
    op.create_table(
        "pull_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_pr_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author_github_username", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("latest_commit_sha", sa.String(40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("state IN ('open','closed','merged')", name="ck_pull_requests_state"),
        sa.CheckConstraint(
            "char_length(latest_commit_sha) = 40", name="ck_pull_requests_sha_length"
        ),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id", "github_pr_number", name="uq_pull_requests_repo_number"
        ),
    )
    op.create_index(
        "ix_pull_requests_repo_number",
        "pull_requests",
        ["repository_id", "github_pr_number"],
        unique=True,
    )

    # ── pull_request_analyses (Corrections #1, #6) ─────────────────────────
    op.create_table(
        "pull_request_analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("pull_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "checklist_is_fallback_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("prompt_template_version", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed','degraded','failed')", name="ck_analyses_status"
        ),
        sa.CheckConstraint(
            "triggered_by IN ('extension','github_action')", name="ck_analyses_triggered_by"
        ),
        sa.CheckConstraint("char_length(commit_sha) = 40", name="ck_analyses_sha_length"),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pull_request_id", "commit_sha", name="uq_analyses_pr_sha"),
    )
    # Cache key (hottest query)
    op.create_index(
        "ix_analyses_pr_sha",
        "pull_request_analyses",
        ["pull_request_id", "commit_sha"],
        unique=True,
    )
    # Correction #6: latest-analysis-for-PR query
    op.create_index(
        "ix_analyses_pr_created", "pull_request_analyses", ["pull_request_id", "created_at"]
    )
    op.create_index("ix_analyses_created_at", "pull_request_analyses", ["created_at"])

    # ── risk_assessments ───────────────────────────────────────────────────
    op.create_table(
        "risk_assessments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("risk_tier", sa.String(20), nullable=False),
        sa.Column("deterministic_score", sa.Numeric(), nullable=False),
        sa.Column("ai_risk_signal", sa.Text(), nullable=True),
        sa.Column("rationale", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("confidence_score", sa.Numeric(), nullable=False),
        sa.CheckConstraint("risk_tier IN ('low','medium','high','critical')", name="ck_risk_tier"),
        sa.CheckConstraint("source IN ('deterministic_only','hybrid')", name="ck_risk_source"),
        sa.CheckConstraint("confidence_score BETWEEN 0 AND 100", name="ck_risk_confidence_range"),
        sa.ForeignKeyConstraint(["analysis_id"], ["pull_request_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id"),
    )
    op.create_index(
        "ix_risk_assessments_analysis_id", "risk_assessments", ["analysis_id"], unique=True
    )
    op.create_index("ix_risk_assessments_risk_tier", "risk_assessments", ["risk_tier"])

    # ── review_suggestions ─────────────────────────────────────────────────
    op.create_table(
        "review_suggestions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("focus_area", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["pull_request_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_suggestions_analysis_id", "review_suggestions", ["analysis_id"])

    # ── reviewer_recommendations ───────────────────────────────────────────
    op.create_table(
        "reviewer_recommendations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommended_github_username", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("confidence_score", sa.Numeric(), nullable=False),
        sa.CheckConstraint("rank >= 1", name="ck_reviewer_rank_positive"),
        sa.CheckConstraint(
            "confidence_score BETWEEN 0 AND 100", name="ck_reviewer_confidence_range"
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["pull_request_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "rank", name="uq_reviewer_analysis_rank"),
    )
    op.create_index(
        "ix_reviewer_recommendations_analysis_rank",
        "reviewer_recommendations",
        ["analysis_id", "rank"],
        unique=True,
    )

    # ── checklist_items (Correction #1: direct FK to analyses) ────────────
    op.create_table(
        "checklist_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("confidence_score", sa.Numeric(), nullable=False),
        sa.Column("trigger_source", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "category IN ('security','performance','exception_handling','null_handling',"
            "'logging','testing','documentation','dependencies','database_changes')",
            name="ck_checklist_category",
        ),
        sa.CheckConstraint(
            "trigger_source IN ('deterministic','ai','both')", name="ck_checklist_trigger_source"
        ),
        sa.CheckConstraint(
            "confidence_score BETWEEN 0 AND 100", name="ck_checklist_confidence_range"
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["pull_request_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "category", name="uq_checklist_analysis_category"),
    )
    op.create_index("ix_checklist_items_analysis_id", "checklist_items", ["analysis_id"])

    # ── checklist_item_completions ─────────────────────────────────────────
    op.create_table(
        "checklist_item_completions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("checklist_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["checklist_item_id"], ["checklist_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checklist_item_id", "user_id", name="uq_completion_item_user"),
    )
    op.create_index("ix_completion_user_id", "checklist_item_completions", ["user_id"])

    # ── feedback (Correction #3: exclusive-arc FKs) ────────────────────────
    op.create_table(
        "feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prediction_type", sa.String(40), nullable=False),
        sa.Column("risk_assessment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewer_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checklist_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "prediction_type IN ('risk_tier','reviewer_recommendation','checklist_item')",
            name="ck_feedback_prediction_type",
        ),
        sa.CheckConstraint("rating IN ('helpful','unhelpful')", name="ck_feedback_rating"),
        sa.CheckConstraint(
            "(prediction_type = 'risk_tier' AND risk_assessment_id IS NOT NULL "
            "AND reviewer_recommendation_id IS NULL AND checklist_item_id IS NULL) OR "
            "(prediction_type = 'reviewer_recommendation' AND reviewer_recommendation_id IS NOT NULL "
            "AND risk_assessment_id IS NULL AND checklist_item_id IS NULL) OR "
            "(prediction_type = 'checklist_item' AND checklist_item_id IS NOT NULL "
            "AND risk_assessment_id IS NULL AND reviewer_recommendation_id IS NULL)",
            name="ck_feedback_exclusive_arc",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["pull_request_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["risk_assessment_id"], ["risk_assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_recommendation_id"], ["reviewer_recommendations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["checklist_item_id"], ["checklist_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_feedback_risk ON feedback (user_id, risk_assessment_id) WHERE risk_assessment_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_feedback_reviewer ON feedback (user_id, reviewer_recommendation_id) WHERE reviewer_recommendation_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_feedback_checklist ON feedback (user_id, checklist_item_id) WHERE checklist_item_id IS NOT NULL"
    )
    op.create_index("ix_feedback_prediction_type", "feedback", ["prediction_type"])
    op.create_index("ix_feedback_analysis_id", "feedback", ["analysis_id"])

    # ── notifications (Correction #2: partial UNIQUE WHERE read_at IS NULL) ─
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pull_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(40), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "notification_type IN ('high_risk_assigned','pr_stale')", name="ck_notification_type"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_notifications_unread_dedup ON notifications "
        "(user_id, pull_request_id, notification_type) WHERE read_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_notifications_unread ON notifications (user_id) WHERE read_at IS NULL"
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])

    # ── user_daily_metrics (Correction #4) ────────────────────────────────
    op.create_table(
        "user_daily_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prs_reviewed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("avg_time_to_first_review_minutes", sa.Numeric(), nullable=True),
        sa.Column(
            "risk_tier_distribution",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "metric_date", name="uq_user_daily_metrics"),
    )
    op.create_index("ix_user_daily_metrics_date", "user_daily_metrics", ["metric_date"])

    # ── repository_daily_metrics (Correction #4) ──────────────────────────
    op.create_table(
        "repository_daily_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prs_reviewed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("avg_time_to_first_review_minutes", sa.Numeric(), nullable=True),
        sa.Column(
            "risk_tier_distribution",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", "metric_date", name="uq_repo_daily_metrics"),
    )
    op.create_index("ix_repo_daily_metrics_date", "repository_daily_metrics", ["metric_date"])

    # ── confidence_calibration ─────────────────────────────────────────────
    op.create_table(
        "confidence_calibration",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("prediction_type", sa.String(40), nullable=False),
        sa.Column("helpful_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unhelpful_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "prediction_type IN ('risk_tier','reviewer_recommendation','checklist_item')",
            name="ck_calibration_prediction_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_type"),
    )
    op.create_index(
        "ix_confidence_calibration_type", "confidence_calibration", ["prediction_type"], unique=True
    )
    # Seed the three rows
    op.execute(
        "INSERT INTO confidence_calibration (prediction_type) VALUES "
        "('risk_tier'), ('reviewer_recommendation'), ('checklist_item')"
    )

    # ── analysis_metrics_log ───────────────────────────────────────────────
    op.create_table(
        "analysis_metrics_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('ai_latency','ai_failure','github_rate_limit','analysis_success','analysis_failure')",
            name="ck_metrics_event_type",
        ),
        # SET NULL — metrics outlive archived analysis rows
        sa.ForeignKeyConstraint(["analysis_id"], ["pull_request_analyses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_metrics_log_event_created", "analysis_metrics_log", ["event_type", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("analysis_metrics_log")
    op.drop_table("confidence_calibration")
    op.drop_table("repository_daily_metrics")
    op.drop_table("user_daily_metrics")
    op.drop_table("notifications")
    op.drop_table("feedback")
    op.drop_table("checklist_item_completions")
    op.drop_table("checklist_items")
    op.drop_table("reviewer_recommendations")
    op.drop_table("review_suggestions")
    op.drop_table("risk_assessments")
    op.drop_table("pull_request_analyses")
    op.drop_table("pull_requests")
    op.drop_table("repository_access")
    op.drop_table("sessions")
    op.drop_table("repositories")
    op.drop_table("users")
