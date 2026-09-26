"""
GitReview AI — GitHub Actions Integration Schemas (LLD A.20)

Request and response shapes for POST /api/actions/analyze.

Security design:
  The shared secret is sent in the X-Actions-Secret header (not in the body)
  so that request bodies can be logged without leaking the credential.
  The header value is compared using hmac.compare_digest to prevent
  timing-based side-channel attacks.

Response design:
  ActionsAnalysisResponse is a compact, comment-ready subset of AnalysisResponse.
  Internal UUIDs, database IDs, and low-level model metadata are deliberately
  excluded — the response is shaped for rendering as a PR comment, not for
  further API chaining.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ActionsAnalyzeRequest(BaseModel):
    """
    Payload sent by the GitHub Actions workflow to trigger PR analysis.

    All fields are required — the workflow has complete context from the
    GitHub Actions event payload (github.repository, github.event.pull_request).

    owner:      Repository owner login (e.g. "octocat")
    name:       Repository name (e.g. "hello-world")
    pr_number:  Pull request number (e.g. 42)
    commit_sha: Full 40-character head commit SHA of the PR at workflow trigger time
    """

    owner: str = Field(description="Repository owner login.")
    name: str = Field(description="Repository name.")
    pr_number: int = Field(ge=1, description="Pull request number (>= 1).")
    commit_sha: str = Field(
        min_length=40,
        max_length=40,
        description="Full 40-character head commit SHA.",
    )


class ActionsChecklistItem(BaseModel):
    category: str
    confidence_score: float
    trigger_source: str


class ActionsReviewerRecommendation(BaseModel):
    username: str
    reason: str
    confidence_score: float


class ActionsAnalysisResponse(BaseModel):
    """
    Compact analysis result shaped for GitHub Actions consumption.

    This is a curated subset of the full AnalysisResponse.
    Internal database IDs and model internals are excluded.
    The 'comment_markdown' field contains a pre-formatted PR comment
    the workflow can post directly via the GitHub API.
    """

    status: str = Field(description="completed | degraded | failed")
    risk_tier: str = Field(description="low | medium | high | critical")
    risk_source: str = Field(description="deterministic_only | hybrid")
    risk_confidence: float = Field(ge=0.0, le=100.0)
    summary: str | None = None
    reviewer_recommendation: ActionsReviewerRecommendation | None = None
    checklist_items: list[ActionsChecklistItem] = Field(default_factory=list)
    checklist_is_fallback: bool = False
    commit_sha: str
    comment_markdown: str = Field(
        description="Pre-formatted Markdown for the PR comment body."
    )
