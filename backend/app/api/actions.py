"""
GitReview AI — GitHub Actions Integration Router (LLD A.20)

Endpoint:
  POST /api/actions/analyze

Authentication:
  X-Actions-Secret header — per-deployment shared secret validated with
  hmac.compare_digest (timing-safe). No user session is involved.

  The GitHub Actions workflow supplies:
    - X-Actions-Secret:  the secret from GitHub repository Secrets
    - X-GitHub-Token:    the workflow's GITHUB_TOKEN (for GitHub API calls)
    - Request body:      owner, name, pr_number, commit_sha

Authorization:
  The repository (owner/name) must already have been authorized by at least
  one GitReview AI user via the extension. This ensures the system only
  analyzes repositories where a user has explicitly opted in.

Design:
  This router is a thin HTTP boundary. All business logic lives in
  app.actions_integration.service. The router:
    1. Reads the two security headers.
    2. Validates the shared secret (raises ActionsAuthError on failure).
    3. Delegates to handle_actions_request().
    4. Returns ActionsAnalysisResponse.

Security notes:
  - The X-Actions-Secret value is NEVER logged, included in error responses,
    or echoed back to the caller.
  - The X-GitHub-Token is also not logged (it has repo-scoped write access).
  - A missing X-Actions-Secret returns 401, not 400, to avoid distinguishing
    between "header missing" and "header wrong" (same information to an attacker).
  - Error messages for auth failures are generic.

Error mapping:
  ActionsAuthError      → 401
  RepositoryNotFoundError → 404
  GitHubRateLimitError  → 429
  GitHubError           → 502
  AnalysisError         → 500
  All typed errors flow through the global GitReviewError handler in main.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions_integration.schemas import ActionsAnalysisResponse, ActionsAnalyzeRequest
from app.actions_integration.service import handle_actions_request, validate_shared_secret
from app.core.database import get_db
from app.core.exceptions import ActionsAuthError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/actions",
    tags=["github_actions"],
)


@router.post(
    "/analyze",
    response_model=ActionsAnalysisResponse,
    summary="GitHub Actions — analyze a pull request",
    description=(
        "Called by the GitReview AI GitHub Actions workflow to trigger PR analysis. "
        "Authenticated via a per-deployment shared secret in the X-Actions-Secret header. "
        "The repository must already be authorized by a GitReview AI user. "
        "Returns a compact analysis result including a pre-formatted Markdown comment."
    ),
    status_code=200,
)
async def actions_analyze(
    request: ActionsAnalyzeRequest,
    x_actions_secret: str | None = Header(default=None, alias="X-Actions-Secret"),
    x_github_token: str | None = Header(default=None, alias="X-GitHub-Token"),
    db: AsyncSession = Depends(get_db),
) -> ActionsAnalysisResponse:
    """
    Analyze a pull request from a GitHub Actions workflow.

    The workflow must provide:
      - X-Actions-Secret: the shared secret configured for this deployment
      - X-GitHub-Token:   the GitHub Actions GITHUB_TOKEN (for GitHub API calls)
      - Body: owner, name, pr_number, commit_sha
    """
    # ── Validate shared secret ─────────────────────────────────────────────────
    # If the header is missing, treat it as an empty string → will fail validation.
    secret_value = x_actions_secret or ""
    try:
        validate_shared_secret(secret_value)
    except ActionsAuthError as exc:
        # Re-raise as HTTPException so the response is 401 with a generic message.
        # Do NOT include the provided secret or the configured secret in the detail.
        logger.warning("actions: shared secret validation failed")
        raise HTTPException(status_code=401, detail=exc.message) from exc

    # ── Validate GitHub token ──────────────────────────────────────────────────
    # The token is needed for GitHub API calls. If absent, we cannot fetch the diff.
    if not x_github_token:
        logger.warning("actions: X-GitHub-Token header missing")
        raise HTTPException(
            status_code=400,
            detail="X-GitHub-Token header is required.",
        )

    logger.info(
        "actions: analyze request repo=%s/%s pr=%d sha=%s",
        request.owner,
        request.name,
        request.pr_number,
        request.commit_sha[:7],
    )

    return await handle_actions_request(
        db=db,
        request=request,
        github_token=x_github_token,
    )
