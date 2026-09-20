"""
GitReview AI — Reviewer Recommendation Module

Ranks candidate reviewers using GitHub-derived ownership and history signals.
Explicitly abstains (no DB write) when evidence is insufficient.

From LLD Part J / SRS FR-5.4:
  - CODEOWNERS matches weighted highest (explicit maintainer signal)
  - Prior review history on same files weighted next
  - Commit contribution frequency weighted lowest
  - Candidates without current repo access are filtered out
  - PR author is always removed from the candidate pool
  - Below minimum evidence threshold → no suggestion, reason stated

LLD Part B.6: ReviewerRankingService — ranking logic only, no direct GitHub fetching.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings


@dataclass
class ReviewerCandidate:
    """A candidate reviewer with their evidence signals."""

    github_username: str
    codeowners_match: bool = False
    review_count_on_files: int = 0  # Prior PR reviews on changed files
    commit_count_on_files: int = 0  # Prior commits to changed files
    has_repo_access: bool = True  # Must be True to be eligible
    score: float = 0.0


@dataclass
class ReviewerRecommendationResult:
    """Result from the Reviewer Recommendation Module."""

    has_suggestion: bool
    # Fields populated only when has_suggestion=True
    recommended_username: str | None = None
    reason: str | None = None
    confidence_score: float | None = None
    rank: int | None = None
    # Optional shortlist for team-lead view (rank 2+)
    shortlist: list[dict] = field(default_factory=list)
    # Populated when has_suggestion=False
    abstain_reason: str | None = None


class ReviewerRankingService:
    """
    Candidate generation, filtering, and ranking per LLD Part J.
    Does not fetch data from GitHub — consumes already-fetched data.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def recommend(
        self,
        changed_files: list[str],
        pr_author_username: str,
        codeowners_map: dict[str, list[str]],
        review_history: dict[str, int],
        commit_history: dict[str, int],
        repo_collaborators: set[str],
    ) -> ReviewerRecommendationResult:
        """
        Generate a reviewer recommendation.

        Args:
            changed_files: File paths changed in the PR.
            pr_author_username: GitHub username of the PR author (excluded from candidates).
            codeowners_map: {file_pattern: [github_username, ...]} from CODEOWNERS.
            review_history: {github_username: review_count} for changed files.
            commit_history: {github_username: commit_count} for changed files.
            repo_collaborators: Set of current, active collaborators with repo access.

        Returns:
            ReviewerRecommendationResult — either a suggestion or explicit abstain.
        """
        candidates = self._generate_candidates(
            changed_files, codeowners_map, review_history, commit_history
        )
        candidates = self._filter_candidates(candidates, pr_author_username, repo_collaborators)
        candidates = self._rank_candidates(candidates)

        if not candidates:
            return ReviewerRecommendationResult(
                has_suggestion=False,
                abstain_reason="No eligible candidates found with repository access.",
            )

        top = candidates[0]
        if top.score < self._settings.reviewer_min_evidence_threshold:
            return ReviewerRecommendationResult(
                has_suggestion=False,
                abstain_reason=(
                    f"Insufficient evidence: best candidate score "
                    f"({top.score:.3f}) is below the minimum threshold "
                    f"({self._settings.reviewer_min_evidence_threshold})."
                ),
            )

        reason = self._build_reason(top, changed_files)
        confidence = self._compute_confidence(top, len(candidates))

        shortlist = [
            {
                "github_username": c.github_username,
                "reason": self._build_reason(c, changed_files),
                "rank": i + 2,
                "confidence_score": self._compute_confidence(c, len(candidates)),
            }
            for i, c in enumerate(candidates[1:4])  # up to 3 additional candidates
        ]

        return ReviewerRecommendationResult(
            has_suggestion=True,
            recommended_username=top.github_username,
            reason=reason,
            confidence_score=confidence,
            rank=1,
            shortlist=shortlist,
        )

    # ── Private ──────────────────────────────────────────────────────────────────

    def _generate_candidates(
        self,
        changed_files: list[str],
        codeowners_map: dict[str, list[str]],
        review_history: dict[str, int],
        commit_history: dict[str, int],
    ) -> list[ReviewerCandidate]:
        """Build the initial candidate pool from all three GitHub-derived sources."""
        pool: dict[str, ReviewerCandidate] = {}

        def _get_or_create(username: str) -> ReviewerCandidate:
            if username not in pool:
                pool[username] = ReviewerCandidate(github_username=username)
            return pool[username]

        # Source 1: CODEOWNERS matches
        for file_path in changed_files:
            for pattern, owners in codeowners_map.items():
                if self._matches_codeowners_pattern(file_path, pattern):
                    for owner in owners:
                        _get_or_create(owner).codeowners_match = True

        # Source 2: Prior reviewers on changed files
        for username, count in review_history.items():
            _get_or_create(username).review_count_on_files += count

        # Source 3: Prior committers to changed files
        for username, count in commit_history.items():
            _get_or_create(username).commit_count_on_files += count

        return list(pool.values())

    def _filter_candidates(
        self,
        candidates: list[ReviewerCandidate],
        pr_author_username: str,
        repo_collaborators: set[str],
    ) -> list[ReviewerCandidate]:
        """
        Remove ineligible candidates:
        1. The PR's own author (never recommend the author to review their own PR)
        2. Anyone without current, verified repo access
        3. Candidates with a single incidental contribution (below minimum evidence)
        """
        filtered = []
        for c in candidates:
            if c.github_username.lower() == pr_author_username.lower():
                continue
            if c.github_username not in repo_collaborators:
                c.has_repo_access = False
                continue
            # Minimum evidence: at least one meaningful signal
            has_meaningful_signal = (
                c.codeowners_match or c.review_count_on_files >= 2 or c.commit_count_on_files >= 2
            )
            if not has_meaningful_signal:
                continue
            filtered.append(c)
        return filtered

    def _rank_candidates(self, candidates: list[ReviewerCandidate]) -> list[ReviewerCandidate]:
        """
        Rank candidates by weighted score.
        Weights (from LLD Part J):
          CODEOWNERS match: 0.6 (explicit maintainer declaration)
          Review frequency:  0.3 (review expertise on files)
          Commit frequency:  0.1 (contribution does not imply review expertise)
        """
        settings = self._settings
        for c in candidates:
            codeowners_score = 1.0 if c.codeowners_match else 0.0
            # Normalize review/commit counts to [0, 1] with a soft cap
            review_score = min(c.review_count_on_files / 10.0, 1.0)
            commit_score = min(c.commit_count_on_files / 20.0, 1.0)

            c.score = (
                codeowners_score * settings.reviewer_codeowners_weight
                + review_score * settings.reviewer_review_history_weight
                + commit_score * settings.reviewer_commit_history_weight
            )

        return sorted(candidates, key=lambda c: c.score, reverse=True)

    def _build_reason(self, candidate: ReviewerCandidate, changed_files: list[str]) -> str:
        """
        Build a concrete, evidence-based reason string.
        SRS FR-5.2: reason must always be grounded in observable history.
        """
        reasons = []
        if candidate.codeowners_match:
            reasons.append("listed as a code owner of changed files")
        if candidate.review_count_on_files >= 2:
            reasons.append(
                f"previously reviewed {candidate.review_count_on_files} PR(s) touching these files"
            )
        if candidate.commit_count_on_files >= 2:
            reasons.append(f"has {candidate.commit_count_on_files} prior commits to these files")
        if not reasons:
            reasons.append("matched on repository contribution history")

        file_summary = f" ({len(changed_files)} file(s) changed)" if changed_files else ""
        return (
            f"{candidate.github_username.capitalize()} is recommended: "
            + "; ".join(reasons)
            + file_summary
            + "."
        )

    def _compute_confidence(self, candidate: ReviewerCandidate, total_candidates: int) -> float:
        """
        Compute a confidence score for this reviewer recommendation.
        Stronger signal → higher confidence. Capped at 85 before calibration.
        """
        base = candidate.score * 100.0  # already 0–1 weighted score → 0–100
        # Bonus for CODEOWNERS (strongest signal)
        if candidate.codeowners_match:
            base = min(base + 15.0, 85.0)
        # Penalty when only one candidate (less comparative evidence)
        if total_candidates == 1:
            base = base * 0.85
        return round(min(float(base), 85.0), 1)

    @staticmethod
    def _matches_codeowners_pattern(file_path: str, pattern: str) -> bool:
        """
        Simple CODEOWNERS glob matching.
        Supports: exact path, directory prefix (auth/), wildcard extension (*.py).
        A full glob implementation would use pathspec library; this covers 90% of cases.
        """
        import fnmatch

        # Remove leading slash from pattern (CODEOWNERS often uses /src/*)
        pattern = pattern.lstrip("/")
        if pattern.endswith("/"):
            # Directory ownership
            return file_path.startswith(pattern) or f"/{pattern}" in f"/{file_path}"
        return fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(file_path, f"*/{pattern}")
