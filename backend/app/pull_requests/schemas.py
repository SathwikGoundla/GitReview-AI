"""
GitReview AI — Pull Request Schemas (Pydantic)

Request and response shapes for /api/repositories/{repository_id}/pulls/* endpoints.

Security:
  - No GitHub OAuth tokens, session hashes, or encrypted credentials are exposed.
  - Diff text is not included in list responses (only available via analysis).
  - Internal UUIDs are included where they are needed to reference resources.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── PR Summary (list view) ─────────────────────────────────────────────────────


class PRSummaryResponse(BaseModel):
    """
    Lightweight PR representation for the list endpoint.
    Does not include diff text or commit history (expensive — only fetched for analysis).
    """

    pr_number: int
    title: str
    author_username: str
    state: str  # open | closed | merged
    head_branch: str
    base_branch: str
    commit_sha: str
    lines_added: int = 0
    lines_removed: int = 0

    model_config = {"from_attributes": True}


class PRListResponse(BaseModel):
    """Response for GET /api/repositories/{repository_id}/pulls."""

    repository_id: uuid.UUID
    owner: str
    name: str
    pull_requests: list[PRSummaryResponse]
    total: int


# ── PR Detail (single PR) ──────────────────────────────────────────────────────


class PRDetailResponse(BaseModel):
    """
    Full PR metadata returned by the detail endpoint.
    Includes changed-file list but NOT raw diff text (too large for a JSON response;
    diff is consumed internally by the analysis pipeline).
    """

    pr_number: int
    title: str
    author_username: str
    state: str
    head_branch: str
    base_branch: str
    commit_sha: str
    lines_added: int = 0
    lines_removed: int = 0
    changed_files: list[str] = Field(default_factory=list)
    commit_messages: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ── Analysis response ──────────────────────────────────────────────────────────


class ReviewSuggestionSchema(BaseModel):
    focus_area: str
    category: str | None = None


class ReviewerRecommendationSchema(BaseModel):
    username: str
    reason: str
    confidence_score: float


class ChecklistItemSchema(BaseModel):
    category: str
    confidence_score: float
    trigger_source: str


class AnalysisResponse(BaseModel):
    """
    Full analysis result returned by POST .../analyze.
    Maps directly from AnalysisResult dataclass.
    """

    analysis_id: uuid.UUID
    pull_request_id: uuid.UUID
    commit_sha: str
    status: str = Field(description="completed | degraded | failed")
    summary: str | None = None
    risk_tier: str = Field(description="low | medium | high | critical")
    risk_source: str = Field(description="deterministic_only | hybrid")
    risk_rationale: dict
    risk_confidence: float = Field(ge=0.0, le=100.0)
    review_suggestions: list[ReviewSuggestionSchema] = Field(default_factory=list)
    reviewer_recommendation: ReviewerRecommendationSchema | None = None
    checklist_items: list[ChecklistItemSchema] = Field(default_factory=list)
    checklist_is_fallback: bool = False
    triggered_by: str
    model_name: str
    prompt_template_version: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Analyze request ────────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """
    Optional body for POST .../analyze.
    All fields are optional — the endpoint can be called with an empty body.
    """

    triggered_by: str = Field(
        default="extension",
        description="Identifies the caller: 'extension' or 'github_action'.",
    )
