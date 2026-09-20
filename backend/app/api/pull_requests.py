"""
GitReview AI — Pull Request Router (LLD A.6 / A.7)

Endpoints:
  GET  /api/repositories/{repository_id}/pulls
      List PRs in an authorized repository (live from GitHub).

  GET  /api/repositories/{repository_id}/pulls/{pull_number}
      Fetch full metadata for a specific PR.

  POST /api/repositories/{repository_id}/pulls/{pull_number}/analyze
      Run (or retrieve from cache) the full AI analysis pipeline for a PR.

Route design rationale:
  PRs are scoped under repositories in the URL because:
    1. A PR number is only unique within a repository.
    2. Repository authorization must be verified for every PR operation.
    3. REST convention: child resources are nested under their parent.

Authorization:
  Every route requires:
    - X-Session-Token → get_current_user → authenticated User
    - repository_id   → verified against RepositoryAccess (active, non-revoked)
    - The verification is done inside the service layer, not the router.
      The router is thin — it only parses HTTP and delegates.

Error mapping:
  RepositoryNotFoundError   → 404 (raised by service authorization guard)
  PullRequestNotFoundError  → 404
  GitHubNotFoundError       → 404 (re-raised via service)
  GitHubRateLimitError      → 429 (via global GitReviewError handler in main.py)
  GitHubError               → 502
  AnalysisError             → 500
  All typed errors flow through the global GitReviewError handler.

Security:
  - No GitHub token, session hash, or encrypted credential appears in responses.
  - Diff text is NOT returned in list or detail endpoints (consumed internally).
  - Cross-user access is blocked at the service layer via the authorization guard.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.models import User
from app.pull_requests.schemas import (
    AnalysisResponse,
    AnalyzeRequest,
    ChecklistItemSchema,
    PRDetailResponse,
    PRListResponse,
    PRSummaryResponse,
    ReviewerRecommendationSchema,
    ReviewSuggestionSchema,
)
from app.pull_requests.service import (
    analyze_pull_request,
    get_pull_request,
    list_pull_requests,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/repositories/{repository_id}/pulls",
    tags=["pull_requests"],
)


# ── GET /api/repositories/{repository_id}/pulls ───────────────────────────────


@router.get(
    "",
    response_model=PRListResponse,
    summary="List pull requests",
    description=(
        "Returns open pull requests from a repository the user has authorized. "
        "Data is fetched live from GitHub. "
        "The user must have an active (non-revoked) authorization for the repository."
    ),
)
async def list_prs(
    repository_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PRListResponse:
    """List open PRs in an authorized repository."""
    repository, pr_list = await list_pull_requests(
        db=db,
        user=current_user,
        repository_id=repository_id,
    )

    return PRListResponse(
        repository_id=repository.id,
        owner=repository.owner,
        name=repository.name,
        pull_requests=[
            PRSummaryResponse(
                pr_number=pr.pr_number,
                title=pr.pr_title,
                author_username=pr.author_username,
                state=pr.state,
                head_branch=pr.head_branch,
                base_branch=pr.base_branch,
                commit_sha=pr.commit_sha,
                lines_added=pr.lines_added,
                lines_removed=pr.lines_removed,
            )
            for pr in pr_list
        ],
        total=len(pr_list),
    )


# ── GET /api/repositories/{repository_id}/pulls/{pull_number} ─────────────────


@router.get(
    "/{pull_number}",
    response_model=PRDetailResponse,
    summary="Get pull request detail",
    description=(
        "Returns full metadata for a specific pull request. "
        "Includes changed-file list and commit messages. "
        "Diff text is not returned here — it is consumed by the analysis pipeline."
    ),
)
async def get_pr(
    repository_id: uuid.UUID,
    pull_number: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PRDetailResponse:
    """Fetch a specific PR's full metadata."""
    _repository, pr_data = await get_pull_request(
        db=db,
        user=current_user,
        repository_id=repository_id,
        pull_number=pull_number,
    )

    return PRDetailResponse(
        pr_number=pr_data.pr_number,
        title=pr_data.pr_title,
        author_username=pr_data.author_username,
        state=pr_data.state,
        head_branch=pr_data.head_branch,
        base_branch=pr_data.base_branch,
        commit_sha=pr_data.commit_sha,
        lines_added=pr_data.lines_added,
        lines_removed=pr_data.lines_removed,
        changed_files=pr_data.changed_files,
        commit_messages=pr_data.commit_messages,
    )


# ── POST /api/repositories/{repository_id}/pulls/{pull_number}/analyze ─────────


@router.post(
    "/{pull_number}/analyze",
    response_model=AnalysisResponse,
    summary="Analyze a pull request",
    description=(
        "Runs the full AI analysis pipeline for a pull request and returns the result. "
        "If the same PR at the same commit SHA has already been analyzed, the cached "
        "result is returned immediately (no redundant AI calls). "
        "A new commit (push) on the PR triggers a fresh analysis. "
        "The pipeline produces: risk tier, confidence, review suggestions, "
        "reviewer recommendation, and review checklist."
    ),
)
async def analyze_pr(
    repository_id: uuid.UUID,
    pull_number: int,
    body: AnalyzeRequest = Body(default=AnalyzeRequest()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisResponse:
    """Run (or return cached) analysis for a PR."""
    result = await analyze_pull_request(
        db=db,
        user=current_user,
        repository_id=repository_id,
        pull_number=pull_number,
        triggered_by=body.triggered_by,
    )

    return AnalysisResponse(
        analysis_id=result.analysis_id,
        pull_request_id=result.pull_request_id,
        commit_sha=result.commit_sha,
        status=result.status,
        summary=result.summary,
        risk_tier=result.risk_tier,
        risk_source=result.risk_source,
        risk_rationale=result.risk_rationale,
        risk_confidence=result.risk_confidence,
        review_suggestions=[
            ReviewSuggestionSchema(
                focus_area=s["focus_area"],
                category=s.get("category"),
            )
            for s in result.review_suggestions
        ],
        reviewer_recommendation=(
            ReviewerRecommendationSchema(
                username=result.reviewer_recommendation["username"],
                reason=result.reviewer_recommendation["reason"],
                confidence_score=result.reviewer_recommendation["confidence_score"],
            )
            if result.reviewer_recommendation
            else None
        ),
        checklist_items=[
            ChecklistItemSchema(
                category=item["category"],
                confidence_score=item["confidence_score"],
                trigger_source=item["trigger_source"],
            )
            for item in result.checklist_items
        ],
        checklist_is_fallback=result.checklist_is_fallback,
        triggered_by=result.triggered_by,
        model_name=result.model_name,
        prompt_template_version=result.prompt_template_version,
        created_at=result.created_at,
    )
