"""
GitReview AI — Pull Request Service (LLD A.6 / B.2)

Owns the internal representation of a Pull Request and coordinates:
  - Repository authorization verification (user must have active access)
  - PR upsert (get_or_create_pull_request keyed on repository_id + github_pr_number)
  - Analysis triggering via the existing AnalysisOrchestrator

Design rules:
  - Never creates a second GitHub client — uses get_decrypted_token_for_user.
  - Never duplicates orchestrator logic — calls run_analysis() directly.
  - Never bypasses the repository authorization check — every PR operation
    verifies the user has a non-revoked RepositoryAccess row.
  - The PullRequest row is shared data (like Repository): multiple users can
    trigger analyses on the same PR. The analysis cache (commit_sha key) prevents
    redundant AI calls regardless of which user triggers first.
  - Factories for the AnalysisOrchestrator and its dependencies live here so
    the router stays thin. In production these could be injected; for the MVP
    modular monolith they are constructed here once per request.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai_provider.gemini_adapter import GeminiAdapter
from app.analysis.checklist.generator import ChecklistGenerator
from app.analysis.confidence.calculator import ConfidenceCalculator
from app.analysis.orchestrator import AnalysisOrchestrator, AnalysisResult
from app.analysis.prompt.builder import PromptBuilder
from app.analysis.reviewer.service import ReviewerRankingService
from app.analysis.risk.engine import RiskEngine
from app.analysis.validation.validator import AnalysisResponseValidator
from app.auth.service import get_decrypted_token_for_user
from app.core.exceptions import (
    GitHubNotFoundError,
    PullRequestNotFoundError,
    RepositoryNotFoundError,
)
from app.core.models import PullRequest, Repository, RepositoryAccess, User
from app.github_integration.client import GitHubApiClient, PRData

logger = logging.getLogger(__name__)


# ── Authorization guard ───────────────────────────────────────────────────────


async def get_authorized_repository(
    db: AsyncSession,
    user: User,
    repository_id: uuid.UUID,
) -> Repository:
    """
    Verify the calling user has an active (non-revoked) RepositoryAccess row
    for the given repository_id, and return the Repository ORM object.

    Raises:
      RepositoryNotFoundError — repository_id doesn't exist in our DB, or
                                the user never authorized it / access was revoked.
    """
    result = await db.execute(
        select(Repository, RepositoryAccess)
        .join(
            RepositoryAccess,
            RepositoryAccess.repository_id == Repository.id,
        )
        .where(
            Repository.id == repository_id,
            RepositoryAccess.user_id == user.id,
            RepositoryAccess.revoked_at.is_(None),
        )
    )
    row = result.first()
    if row is None:
        raise RepositoryNotFoundError(
            f"Repository not found or not authorized for the current user "
            f"(repository_id={repository_id})."
        )
    repository, _ = row
    return repository


# ── GitHub client factory ──────────────────────────────────────────────────────


def _github_client_for(user: User) -> GitHubApiClient:
    """Construct a GitHubApiClient using the authenticated user's decrypted token."""
    return GitHubApiClient(access_token=get_decrypted_token_for_user(user))


# ── PR upsert ─────────────────────────────────────────────────────────────────


async def get_or_create_pull_request(
    db: AsyncSession,
    repository: Repository,
    pr_data: PRData,
) -> PullRequest:
    """
    Upsert a PullRequest row keyed on (repository_id, github_pr_number).

    If the PR already exists, update title/state/latest_commit_sha so our
    internal record stays current with GitHub.

    Returns the ORM PullRequest with .repository eager-loaded (needed by
    the orchestrator which accesses pull_request.repository.owner etc.).
    """
    result = await db.execute(
        select(PullRequest)
        .options(selectinload(PullRequest.repository))
        .where(
            PullRequest.repository_id == repository.id,
            PullRequest.github_pr_number == pr_data.pr_number,
        )
    )
    pr = result.scalars().first()

    now = datetime.now(UTC)

    if pr is None:
        pr = PullRequest(
            repository_id=repository.id,
            github_pr_number=pr_data.pr_number,
            title=pr_data.pr_title,
            author_github_username=pr_data.author_username,
            state=pr_data.state,
            latest_commit_sha=pr_data.commit_sha,
            created_at=now,
            updated_at=now,
        )
        db.add(pr)
        await db.flush()
        # Reload with relationship
        result = await db.execute(
            select(PullRequest)
            .options(selectinload(PullRequest.repository))
            .where(PullRequest.id == pr.id)
        )
        pr = result.scalars().one()
    else:
        # Refresh mutable fields
        pr.title = pr_data.pr_title
        pr.state = pr_data.state
        pr.latest_commit_sha = pr_data.commit_sha
        pr.updated_at = now
        await db.flush()

    return pr


# ── Orchestrator factory ──────────────────────────────────────────────────────


def _build_orchestrator() -> AnalysisOrchestrator:
    """
    Construct the AnalysisOrchestrator with all its dependencies.
    For the MVP modular monolith this is done per request (stateless).
    Components are cheap to instantiate; the expensive work is I/O inside them.
    """
    return AnalysisOrchestrator(
        ai_provider=GeminiAdapter(),
        prompt_builder=PromptBuilder(),
        validator=AnalysisResponseValidator(),
        risk_engine=RiskEngine(),
        confidence_calculator=ConfidenceCalculator(),
        reviewer_service=ReviewerRankingService(),
        checklist_generator=ChecklistGenerator(),
    )


# ── Public service functions ──────────────────────────────────────────────────


async def list_pull_requests(
    db: AsyncSession,
    user: User,
    repository_id: uuid.UUID,
    state: str = "open",
) -> tuple[Repository, list[PRData]]:
    """
    List PRs from a GitHub repository the user is authorized to use.

    Steps:
      1. Verify user has active access to repository_id.
      2. Call GitHub to list open (or filtered) PRs.
      3. Return (repository, list[PRData]).

    The list comes from GitHub live — not from our DB — because PR state
    changes frequently and we do not poll GitHub. The PR list is a thin
    passthrough to avoid stale data in the extension queue.

    Raises:
      RepositoryNotFoundError — not authorized
      GitHubNotFoundError — repo no longer accessible on GitHub
      GitHubRateLimitError — rate limited
    """
    repository = await get_authorized_repository(db, user, repository_id)
    client = _github_client_for(user)

    import httpx  # noqa: PLC0415

    from app.github_integration.client import _GITHUB_API  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(
            f"{_GITHUB_API}/repos/{repository.owner}/{repository.name}/pulls",
            headers={
                "Authorization": f"Bearer {get_decrypted_token_for_user(user)}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"state": state, "per_page": 30, "sort": "updated", "direction": "desc"},
        )

    client._raise_for_status(resp)

    raw_prs = resp.json()
    pr_summaries: list[PRData] = []
    for raw in raw_prs:
        head_sha = raw["head"]["sha"]
        pr_state = "merged" if raw.get("merged") else raw.get("state", "open")
        pr_summaries.append(
            PRData(
                repo_owner=repository.owner,
                repo_name=repository.name,
                github_repo_id=0,  # not needed for list display
                pr_number=raw["number"],
                pr_title=raw["title"],
                author_username=raw["user"]["login"],
                base_branch=raw["base"]["ref"],
                head_branch=raw["head"]["ref"],
                commit_sha=head_sha,
                state=pr_state,
                changed_files=[],  # not fetched for list — only for analysis
                diff_text="",
                lines_added=raw.get("additions", 0),
                lines_removed=raw.get("deletions", 0),
                commit_messages=[],
            )
        )

    return repository, pr_summaries


async def get_pull_request(
    db: AsyncSession,
    user: User,
    repository_id: uuid.UUID,
    pull_number: int,
) -> tuple[Repository, PRData]:
    """
    Fetch a single PR's full metadata from GitHub.

    Steps:
      1. Verify user access.
      2. Fetch PR data from GitHub (full PRData).
      3. Return (repository, PRData).

    Raises:
      RepositoryNotFoundError — not authorized
      PullRequestNotFoundError — PR does not exist (maps GitHubNotFoundError)
      GitHubRateLimitError — rate limited
    """
    repository = await get_authorized_repository(db, user, repository_id)
    client = _github_client_for(user)

    try:
        pr_data = await client.fetch_pull_request_data(
            repository.owner, repository.name, pull_number
        )
    except GitHubNotFoundError:
        raise PullRequestNotFoundError(
            f"Pull request #{pull_number} was not found in {repository.owner}/{repository.name}."
        )

    return repository, pr_data


async def analyze_pull_request(
    db: AsyncSession,
    user: User,
    repository_id: uuid.UUID,
    pull_number: int,
    triggered_by: str = "extension",
) -> AnalysisResult:
    """
    Run the full analysis pipeline for a PR.

    Steps:
      1. Verify user access to repository_id.
      2. Fetch PR data from GitHub (includes diff, commits, etc.).
      3. Upsert PullRequest ORM record.
      4. Invoke AnalysisOrchestrator.run_analysis() — which internally:
           a. Checks the commit-SHA cache.
           b. Calls AI, validates, retries.
           c. Runs deterministic + hybrid risk.
           d. Computes confidence.
           e. Recommends reviewer.
           f. Generates checklist.
           g. Persists atomically.
      5. Return AnalysisResult.

    Idempotency:
      The orchestrator's cache check (step 4a) means calling this twice with
      the same PR at the same commit SHA returns the cached result without
      re-invoking the AI. A new commit (new SHA) produces a new analysis.

    Raises:
      RepositoryNotFoundError — not authorized
      PullRequestNotFoundError — PR does not exist on GitHub
      GitHubRateLimitError — rate limited
      AnalysisError (and subtypes) — pipeline failure
    """
    repository = await get_authorized_repository(db, user, repository_id)
    client = _github_client_for(user)

    # Fetch full PR data (diff + metadata)
    try:
        pr_data = await client.fetch_pull_request_data(
            repository.owner, repository.name, pull_number
        )
    except GitHubNotFoundError:
        raise PullRequestNotFoundError(
            f"Pull request #{pull_number} was not found in "
            f"{repository.owner}/{repository.name}."
        )

    # Upsert internal PR record with .repository eager-loaded
    pull_request = await get_or_create_pull_request(db, repository, pr_data)

    # Build orchestrator and run
    orchestrator = _build_orchestrator()
    result = await orchestrator.run_analysis(
        db=db,
        pull_request=pull_request,
        commit_sha=pr_data.commit_sha,
        github_client=client,
        triggered_by=triggered_by,
    )

    logger.info(
        "Analysis complete. user=%s repo=%s/%s pr=#%d sha=%s status=%s risk=%s",
        user.github_username,
        repository.owner,
        repository.name,
        pull_number,
        pr_data.commit_sha[:8],
        result.status,
        result.risk_tier,
    )

    return result
