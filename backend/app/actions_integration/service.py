"""
GitReview AI — GitHub Actions Integration Service (LLD A.20 / HLD Section 11)

This module is a thin adapter in front of the existing PR Analysis Orchestrator.
It does NOT duplicate any analysis logic — it:

  1. Validates the per-repository shared secret (the only Actions-specific auth).
  2. Looks up the repository by (owner, name) — no user session is involved.
  3. Delegates to the same AnalysisOrchestrator used by the extension path.
  4. Formats the result as a Markdown comment ready for GitHub to post.

LLD A.20 quote:
  "A thin adapter in front of the same Orchestrator used by the Extension path."

Security:
  - Shared secret compared with hmac.compare_digest (timing-safe).
  - If ACTIONS_SHARED_SECRET is empty in settings, all Actions requests are
    rejected. This prevents the endpoint from being usable in development
    without explicit configuration.
  - The secret is NEVER logged, included in error messages, or returned in
    any response body.
  - Error messages for invalid secrets are deliberately generic to prevent
    oracle attacks (is the secret wrong, or does the repo not exist?).

Comment idempotency (HLD Section 11):
  The workflow script handles idempotency by searching for an existing
  GitReview AI marker comment and editing it in place. The backend does not
  need to track comment IDs — that responsibility belongs to the workflow layer,
  which has access to the GitHub API and GITHUB_TOKEN. This is the simplest
  correct design: the backend produces the analysis result and comment text;
  the workflow decides whether to create or edit.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions_integration.schemas import (
    ActionsAnalysisResponse,
    ActionsAnalyzeRequest,
    ActionsChecklistItem,
    ActionsReviewerRecommendation,
)
from app.ai_provider.gemini_adapter import GeminiAdapter
from app.analysis.checklist.generator import ChecklistGenerator
from app.analysis.confidence.calculator import ConfidenceCalculator
from app.analysis.orchestrator import AnalysisOrchestrator
from app.analysis.prompt.builder import PromptBuilder
from app.analysis.reviewer.service import ReviewerRankingService
from app.analysis.risk.engine import RiskEngine
from app.analysis.validation.validator import AnalysisResponseValidator
from app.core.config import get_settings
from app.core.exceptions import ActionsAuthError, RepositoryNotFoundError
from app.core.models import PullRequest, Repository
from app.github_integration.client import GitHubApiClient

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Marker used by the workflow to find and edit existing comments ─────────────
# Must match the marker in the workflow file exactly.
COMMENT_MARKER = "<!-- gitreview-ai-bot -->"

# Risk tier → emoji mapping for the comment header
_TIER_EMOJI = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "critical": "🔴",
}

# Confidence band labels (matches LLD Part I display convention)
_CONFIDENCE_BAND = {
    "high": (80, 100),
    "moderate": (50, 79),
    "low": (0, 49),
}


def _confidence_label(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 50:
        return "Moderate"
    return "Low"


# ── Secret validation ──────────────────────────────────────────────────────────


def validate_shared_secret(provided_secret: str) -> None:
    """
    Validate the provided shared secret against the configured value.

    Uses hmac.compare_digest for timing-safe comparison to prevent
    secret-oracle attacks.

    Raises:
        ActionsAuthError — secret is wrong, empty, or the endpoint is disabled.
    """
    configured = settings.actions_shared_secret
    if not configured:
        # Endpoint is disabled if no secret is configured.
        raise ActionsAuthError(
            "GitHub Actions endpoint is not configured on this deployment.",
            detail="Set ACTIONS_SHARED_SECRET in the backend environment variables.",
        )

    # Both sides must be bytes for hmac.compare_digest.
    if not hmac.compare_digest(
        hashlib.sha256(provided_secret.encode()).digest(),
        hashlib.sha256(configured.encode()).digest(),
    ):
        # Generic message: do not confirm whether the secret format is wrong
        # or whether the secret value is close/far from the correct value.
        raise ActionsAuthError(
            "Invalid shared secret.",
            detail="Check that GITREVIEW_SHARED_SECRET in GitHub Secrets matches "
            "ACTIONS_SHARED_SECRET in the backend environment variables.",
        )


# ── Repository lookup ──────────────────────────────────────────────────────────


async def get_repository_by_owner_name(
    db: AsyncSession,
    owner: str,
    name: str,
) -> Repository:
    """
    Look up a Repository by (owner, name).

    Actions requests identify the repository by its GitHub name, not an
    internal UUID (no user session → no pre-resolved repository_id).

    Raises:
        RepositoryNotFoundError — repository has never been authorized in
                                  GitReview AI (no row in the repositories table).
    """
    result = await db.execute(
        select(Repository).where(
            Repository.owner == owner,
            Repository.name == name,
        )
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise RepositoryNotFoundError(
            f"Repository {owner}/{name} has not been authorized in GitReview AI.",
            detail=(
                "A user with repository access must authorize this repository "
                "via the GitReview AI extension before the Actions integration "
                "can analyze its pull requests."
            ),
        )
    return repo


# ── Orchestrator factory (same pattern as pull_requests/service.py) ────────────


def _build_orchestrator(github_token: str) -> AnalysisOrchestrator:
    """
    Build the AnalysisOrchestrator and its full dependency tree for one request.

    This is identical to the factory in pull_requests/service.py — kept in sync
    deliberately. For Actions requests, the GitHub token comes from the Actions
    workflow's GITHUB_TOKEN context passed in the request (not from an OAuth
    session), so it is provided directly rather than decrypted from the DB.

    LLD A.20: "A thin adapter in front of the same Orchestrator."
    """
    settings = get_settings()
    client = GitHubApiClient(
        access_token=github_token,
        api_base=settings.github_api_base,
    )
    return AnalysisOrchestrator(
        github_client=client,
        ai_provider=GeminiAdapter(),
        prompt_builder=PromptBuilder(),
        validator=AnalysisResponseValidator(),
        risk_engine=RiskEngine(),
        confidence_calculator=ConfidenceCalculator(),
        reviewer_service=ReviewerRankingService(github_client=client),
        checklist_generator=ChecklistGenerator(),
    )


# ── Comment formatter ──────────────────────────────────────────────────────────


def format_pr_comment(
    result_data: dict,
    owner: str,
    name: str,
    pr_number: int,
) -> str:
    """
    Format the analysis result as a Markdown PR comment.

    Design rules (per Step 19 scope, section 8):
    - Communicate useful review-assistance information
    - Do NOT dump the raw AI response
    - Do NOT expose internal prompts or database IDs
    - Clearly frame output as review assistance, not a merge gate
    - Include the COMMENT_MARKER so the workflow can find and edit it
    """
    tier = result_data.get("risk_tier", "unknown")
    emoji = _TIER_EMOJI.get(tier, "⚪")
    confidence = result_data.get("risk_confidence", 0.0)
    confidence_label = _confidence_label(confidence)
    status = result_data.get("status", "unknown")
    summary = result_data.get("summary")
    source = result_data.get("risk_source", "hybrid")
    commit_sha = result_data.get("commit_sha", "")
    short_sha = commit_sha[:7] if commit_sha else "unknown"

    lines = [
        COMMENT_MARKER,
        f"## {emoji} GitReview AI — Risk Assessment",
        "",
        f"**Repository:** `{owner}/{name}` &nbsp;|&nbsp; "
        f"**PR:** #{pr_number} &nbsp;|&nbsp; "
        f"**Commit:** `{short_sha}`",
        "",
    ]

    if status == "failed":
        lines += [
            "> ⚠️ **Analysis failed.** The AI pipeline could not complete for this commit.",
            "> Please check the GitReview AI workflow logs for details.",
            "",
        ]
        lines.append("---")
        lines.append(
            "_This comment is generated by [GitReview AI](https://github.com). "
            "It is review assistance, not a merge gate._"
        )
        return "\n".join(lines)

    # Risk tier
    tier_display = tier.upper() if tier else "UNKNOWN"
    source_note = "(deterministic signals only)" if source == "deterministic_only" else ""
    lines += [
        f"### Risk Tier: **{tier_display}** {emoji}",
        f"**Confidence:** {confidence:.0f}% ({confidence_label}) {source_note}",
        "",
    ]

    # Summary
    if summary:
        lines += [
            "### Summary",
            summary,
            "",
        ]

    # Degraded notice
    if status == "degraded":
        lines += [
            "> ℹ️ **Note:** AI signals were unavailable for this analysis. "
            "The risk tier is based on deterministic signals only.",
            "",
        ]

    # Rationale factors
    rationale = result_data.get("risk_rationale", {})
    factors = rationale.get("factors", []) if isinstance(rationale, dict) else []
    if factors:
        lines += ["### Risk Factors", ""]
        for f in factors[:5]:  # Cap at 5 factors to keep comment concise
            if isinstance(f, dict):
                label = f.get("factor", f.get("name", ""))
                detail = f.get("detail", f.get("description", ""))
                if label:
                    lines.append(f"- **{label}**: {detail}" if detail else f"- {label}")
        lines.append("")

    # Reviewer recommendation
    reviewer = result_data.get("reviewer_recommendation")
    if reviewer and isinstance(reviewer, dict):
        username = reviewer.get("username", "")
        reason = reviewer.get("reason", "")
        rev_conf = reviewer.get("confidence_score", 0.0)
        lines += [
            "### Suggested Reviewer",
            f"**@{username}** ({_confidence_label(rev_conf)} confidence)",
            f"> {reason}",
            "",
        ]

    # Checklist summary
    checklist = result_data.get("checklist_items", [])
    is_fallback = result_data.get("checklist_is_fallback", False)
    if checklist:
        fallback_note = " *(baseline — AI signal unavailable)*" if is_fallback else ""
        lines += [
            f"### Review Checklist{fallback_note}",
            "",
        ]
        for item in checklist:
            if isinstance(item, dict):
                cat = item.get("category", "").replace("_", " ").title()
                src = item.get("trigger_source", "")
                src_badge = (
                    "🔒 required"
                    if src == "deterministic"
                    else "🤖 AI" if src == "ai" else "🔒+🤖"
                )
                lines.append(f"- [ ] **{cat}** — {src_badge}")
        lines.append("")

    lines += [
        "---",
        "_This comment is generated by [GitReview AI](https://github.com). "
        "It is review assistance, not a merge gate. "
        "Risk tiers are based on code signals and AI analysis — always apply human judgment._",
    ]

    return "\n".join(lines)


# ── Main service function ──────────────────────────────────────────────────────


async def handle_actions_request(
    db: AsyncSession,
    request: ActionsAnalyzeRequest,
    github_token: str,
) -> ActionsAnalysisResponse:
    """
    Handle one GitHub Actions analysis request end-to-end.

    Steps:
    1. Look up the repository by (owner, name) — must already be authorized.
    2. Get or create the PullRequest ORM row.
    3. Build and run the AnalysisOrchestrator (same as extension path).
    4. Format the result as a Markdown PR comment.
    5. Return ActionsAnalysisResponse.

    The github_token used here is the Actions workflow's GITHUB_TOKEN,
    scoped to the repository. It is different from a user OAuth token —
    it has repository-scoped read access and can post PR comments.
    It is NEVER stored in the database.

    LLD A.20: "Validates the shared secret, invokes the Orchestrator,
    formats the result for comment/label posting."
    """
    # Look up the repository (must already exist from a prior extension authorization)
    repo = await get_repository_by_owner_name(db, request.owner, request.name)

    # Upsert the PullRequest row (same pattern as pull_requests/service.py)
    await _upsert_pull_request(
        db=db,
        repo=repo,
        pr_number=request.pr_number,
        commit_sha=request.commit_sha,
    )

    # Build and run the orchestrator (reuses the full analysis pipeline)
    orchestrator = _build_orchestrator(github_token=github_token)
    result = await orchestrator.run_analysis(
        db=db,
        repository_id=repo.id,
        owner=request.owner,
        repo_name=request.name,
        pr_number=request.pr_number,
        commit_sha=request.commit_sha,
        triggered_by="github_action",
    )

    # Build a serialisable dict for the comment formatter
    result_dict = {
        "status": result.status,
        "risk_tier": result.risk_tier,
        "risk_source": result.risk_source,
        "risk_rationale": result.risk_rationale,
        "risk_confidence": result.risk_confidence,
        "summary": result.summary,
        "commit_sha": result.commit_sha,
        "checklist_items": result.checklist_items,
        "checklist_is_fallback": result.checklist_is_fallback,
        "reviewer_recommendation": result.reviewer_recommendation,
    }

    comment_md = format_pr_comment(
        result_data=result_dict,
        owner=request.owner,
        name=request.name,
        pr_number=request.pr_number,
    )

    reviewer_schema = None
    if result.reviewer_recommendation:
        reviewer_schema = ActionsReviewerRecommendation(
            username=result.reviewer_recommendation["username"],
            reason=result.reviewer_recommendation["reason"],
            confidence_score=result.reviewer_recommendation["confidence_score"],
        )

    return ActionsAnalysisResponse(
        status=result.status,
        risk_tier=result.risk_tier,
        risk_source=result.risk_source,
        risk_confidence=result.risk_confidence,
        summary=result.summary,
        reviewer_recommendation=reviewer_schema,
        checklist_items=[
            ActionsChecklistItem(
                category=item["category"],
                confidence_score=item["confidence_score"],
                trigger_source=item["trigger_source"],
            )
            for item in result.checklist_items
        ],
        checklist_is_fallback=result.checklist_is_fallback,
        commit_sha=result.commit_sha,
        comment_markdown=comment_md,
    )


# ── PullRequest upsert (mirrors pull_requests/service.py) ─────────────────────


async def _upsert_pull_request(
    db: AsyncSession,
    repo: Repository,
    pr_number: int,
    commit_sha: str,
) -> PullRequest:
    """
    Get or create a PullRequest row keyed on (repository_id, github_pr_number).
    Updates latest_commit_sha if the PR already exists.

    For Actions requests we don't have a rich PRData object yet (that comes
    from the orchestrator's GitHub fetch). We write a minimal row here so the
    orchestrator's cache check can find the PR by ID; the orchestrator will
    populate full metadata from GitHub during its data-fetch phase.
    """
    result = await db.execute(
        select(PullRequest).where(
            PullRequest.repository_id == repo.id,
            PullRequest.github_pr_number == pr_number,
        )
    )
    pr = result.scalar_one_or_none()

    if pr is None:
        pr = PullRequest(
            repository_id=repo.id,
            github_pr_number=pr_number,
            title="",  # Populated by orchestrator from GitHub
            author_github_username="",  # Populated by orchestrator from GitHub
            state="open",
            latest_commit_sha=commit_sha,
        )
        db.add(pr)
        await db.flush()
        logger.info(
            "actions: created PR row repo_id=%s pr_number=%d", repo.id, pr_number
        )
    elif pr.latest_commit_sha != commit_sha:
        pr.latest_commit_sha = commit_sha
        logger.info(
            "actions: updated commit SHA pr_id=%s sha=%s", pr.id, commit_sha[:7]
        )

    return pr
