"""
GitReview AI — PR Analysis Orchestrator

Coordinates the full analysis pipeline for one PR at one commit SHA.
LLD Part A.7 / B.4: Central coordinator, invoked identically by Extension
and GitHub Actions paths.

Pipeline order (HLD Section 2):
  1. Check commit-SHA cache
  2. Fetch PR data from GitHub (once)
  3. Build structured prompt (PromptBuilder)
  4. Call AI Provider (single pass for all outputs)
  5. Validate AI response (AnalysisResponseValidator)
  6. Compute deterministic signals (RiskEngine)
  7. Combine into hybrid risk result (RiskEngine)
  8. Compute confidence scores (ConfidenceCalculator)
  9. Recommend reviewer (ReviewerRankingService)
  10. Generate checklist (ChecklistGenerator)
  11. Persist combined result atomically
  12. Return result

Fail-toward-omission: any stage failure halts with a typed error.
No partial result is ever assembled or returned.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_provider.interface import AIProviderInterface
from app.analysis.checklist.generator import ChecklistGenerator, ChecklistResult
from app.analysis.confidence.calculator import (
    CalibrationData,
    ConfidenceCalculator,
    ConfidenceInputs,
)
from app.analysis.prompt.builder import NormalizedPRData, PromptBuilder
from app.analysis.reviewer.service import ReviewerRankingService, ReviewerRecommendationResult
from app.analysis.risk.engine import RiskEngine, RiskResult
from app.analysis.validation.validator import AnalysisResponseValidator
from app.core.logging import log_event
from app.core.models import (
    ChecklistItem,
    PullRequest,
    PullRequestAnalysis,
    ReviewerRecommendation,
    ReviewSuggestion,
    RiskAssessment,
)
from app.github_integration.client import GitHubApiClient, PRData

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_VERSION = "v1.0"
MODEL_NAME = "gemini-2.5-flash"


@dataclass
class AnalysisResult:
    """Complete, validated analysis result returned to callers."""

    analysis_id: uuid.UUID
    pull_request_id: uuid.UUID
    commit_sha: str
    status: str  # completed | degraded | failed
    summary: str | None
    risk_tier: str
    risk_source: str
    risk_rationale: dict
    risk_confidence: float
    # UUID of the persisted risk_assessments row — required by the feedback
    # endpoint as prediction_reference_id when prediction_type="risk_tier".
    # None only when the analysis failed before persisting a risk assessment.
    risk_assessment_id: uuid.UUID | None = None
    review_suggestions: list[dict] = field(default_factory=list)
    reviewer_recommendation: dict | None = None
    checklist_items: list[dict] = field(default_factory=list)
    checklist_is_fallback: bool = False
    triggered_by: str = "extension"
    model_name: str = MODEL_NAME
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AnalysisOrchestrator:
    """
    Coordinates the full analysis pipeline. Stateless per invocation.
    Contains no AI or GitHub logic itself — pure coordination.
    """

    def __init__(
        self,
        ai_provider: AIProviderInterface,
        prompt_builder: PromptBuilder,
        validator: AnalysisResponseValidator,
        risk_engine: RiskEngine,
        confidence_calculator: ConfidenceCalculator,
        reviewer_service: ReviewerRankingService,
        checklist_generator: ChecklistGenerator,
    ) -> None:
        self._ai = ai_provider
        self._prompt_builder = prompt_builder
        self._validator = validator
        self._risk_engine = risk_engine
        self._confidence_calc = confidence_calculator
        self._reviewer_service = reviewer_service
        self._checklist_gen = checklist_generator

    async def run_analysis(
        self,
        db: AsyncSession,
        pull_request: PullRequest,
        commit_sha: str,
        github_client: GitHubApiClient,
        triggered_by: str = "extension",
        calibration_data: dict[str, CalibrationData] | None = None,
    ) -> AnalysisResult:
        """
        Run the full analysis pipeline for a PR at a specific commit SHA.

        Args:
            db: Database session for cache lookup and result persistence.
            pull_request: Internal PullRequest ORM record.
            commit_sha: Full 40-char SHA to analyze.
            github_client: Authenticated GitHub API client.
            triggered_by: 'extension' or 'github_action'.
            calibration_data: Optional calibration aggregates per prediction type.

        Returns:
            AnalysisResult — always complete or raises a typed exception.
        """
        # Step 1: Check commit-SHA cache
        cached = await self._check_cache(db, pull_request.id, commit_sha)
        if cached is not None:
            log_event(
                logger,
                "analysis_cache_hit",
                {
                    "pull_request_id": str(pull_request.id),
                    "commit_sha": commit_sha[:8],
                },
            )
            return cached

        # Step 2: Fetch PR data from GitHub (once per pipeline invocation)
        repo = pull_request.repository
        pr_data = await github_client.fetch_pull_request_data(
            repo.owner, repo.name, pull_request.github_pr_number
        )
        codeowners_map = await github_client.fetch_codeowners(repo.owner, repo.name)
        commit_history, review_history = await github_client.fetch_contribution_history(
            repo.owner, repo.name, pr_data.changed_files
        )
        collaborators = await github_client.fetch_collaborators(repo.owner, repo.name)

        # Step 3: Build prompt
        normalized = self._build_normalized_pr_data(pr_data)
        built_prompt = self._prompt_builder.build_prompt(normalized)

        if built_prompt.injection_signals_detected:
            log_event(
                logger,
                "prompt_injection_signal",
                {
                    "pull_request_id": str(pull_request.id),
                    "commit_sha": commit_sha[:8],
                },
            )

        # Steps 4 + 5: Call AI, validate, retry once on failure
        validated_ai, required_retry, ai_available = await self._call_ai_with_retry(
            built_prompt.prompt_text, pr_data.changed_files
        )

        # Step 6: Compute deterministic signals
        det_signals = self._risk_engine.compute_deterministic_signals(
            pr_data.changed_files, pr_data.lines_added, pr_data.lines_removed
        )

        # Step 7: Hybrid risk result
        ai_risk_signal = validated_ai.get("ai_risk_signal") if validated_ai else None
        risk_result = self._risk_engine.assess_risk(det_signals, ai_risk_signal)

        # Step 8: Confidence scores
        cal = calibration_data or {}
        risk_confidence = self._confidence_calc.compute_confidence(
            ConfidenceInputs(
                prediction_type="risk_tier",
                ai_self_report=validated_ai.get("self_reported_confidence", 50)
                if validated_ai
                else 30,
                ai_tier=ai_risk_signal,
                deterministic_tier=risk_result.risk_tier,
                required_retry=required_retry,
                evidence_complete=ai_available,
                calibration=cal.get("risk_tier"),
            )
        )

        # Step 9: Reviewer recommendation
        reviewer_result = self._reviewer_service.recommend(
            changed_files=pr_data.changed_files,
            pr_author_username=pr_data.author_username,
            codeowners_map=codeowners_map,
            review_history=review_history,
            commit_history=commit_history,
            repo_collaborators=collaborators,
        )

        # Step 10: Checklist
        ai_checklist = validated_ai.get("checklist") if validated_ai else None
        checklist_result = self._checklist_gen.generate_checklist(
            pr_data.changed_files, ai_checklist
        )

        # Step 11: Persist atomically
        analysis = await self._persist_result(
            db=db,
            pull_request=pull_request,
            commit_sha=commit_sha,
            pr_data=pr_data,
            validated_ai=validated_ai,
            risk_result=risk_result,
            risk_confidence=risk_confidence,
            reviewer_result=reviewer_result,
            checklist_result=checklist_result,
            triggered_by=triggered_by,
            status="completed" if ai_available else "degraded",
        )

        return AnalysisResult(
            analysis_id=analysis.id,
            pull_request_id=pull_request.id,
            commit_sha=commit_sha,
            status=analysis.status,
            summary=analysis.summary,
            risk_tier=risk_result.risk_tier,
            risk_source=risk_result.source,
            risk_rationale=risk_result.rationale,
            risk_confidence=risk_confidence,
            risk_assessment_id=(
                analysis.risk_assessment.id if analysis.risk_assessment else None
            ),
            review_suggestions=[
                {"focus_area": s.focus_area, "category": s.category}
                for s in analysis.review_suggestions
            ],
            reviewer_recommendation=(
                {
                    "username": reviewer_result.recommended_username,
                    "reason": reviewer_result.reason,
                    "confidence_score": reviewer_result.confidence_score,
                }
                if reviewer_result.has_suggestion
                else None
            ),
            checklist_items=[
                {
                    "category": item.category,
                    "confidence_score": float(item.confidence_score),
                    "trigger_source": item.trigger_source,
                }
                for item in analysis.checklist_items
            ],
            checklist_is_fallback=analysis.checklist_is_fallback_default,
            triggered_by=triggered_by,
        )

    # ── Private ──────────────────────────────────────────────────────────────────

    async def _check_cache(
        self, db: AsyncSession, pull_request_id: uuid.UUID, commit_sha: str
    ) -> AnalysisResult | None:
        """Check the commit-SHA cache (pull_request_analyses table)."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(PullRequestAnalysis)
            .where(
                PullRequestAnalysis.pull_request_id == pull_request_id,
                PullRequestAnalysis.commit_sha == commit_sha,
                PullRequestAnalysis.status != "failed",
            )
            .options(
                selectinload(PullRequestAnalysis.risk_assessment),
                selectinload(PullRequestAnalysis.review_suggestions),
                selectinload(PullRequestAnalysis.reviewer_recommendations),
                selectinload(PullRequestAnalysis.checklist_items),
            )
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        risk = row.risk_assessment
        primary_reviewer = next((r for r in row.reviewer_recommendations if r.rank == 1), None)
        return AnalysisResult(
            analysis_id=row.id,
            pull_request_id=pull_request_id,
            commit_sha=commit_sha,
            status=row.status,
            summary=row.summary,
            risk_tier=risk.risk_tier if risk else "low",
            risk_source=risk.source if risk else "deterministic_only",
            risk_rationale=risk.rationale if risk else {"factors": []},
            risk_confidence=float(risk.confidence_score) if risk else 50.0,
            risk_assessment_id=risk.id if risk else None,
            review_suggestions=[
                {"focus_area": s.focus_area, "category": s.category} for s in row.review_suggestions
            ],
            reviewer_recommendation=(
                {
                    "username": primary_reviewer.recommended_github_username,
                    "reason": primary_reviewer.reason,
                    "confidence_score": float(primary_reviewer.confidence_score),
                }
                if primary_reviewer
                else None
            ),
            checklist_items=[
                {
                    "category": item.category,
                    "confidence_score": float(item.confidence_score),
                    "trigger_source": item.trigger_source,
                }
                for item in row.checklist_items
            ],
            checklist_is_fallback=row.checklist_is_fallback_default,
            triggered_by=row.triggered_by,
            created_at=row.created_at,
        )

    async def _call_ai_with_retry(
        self, prompt: str, changed_files: list[str]
    ) -> tuple[dict | None, bool, bool]:
        """
        Call AI Provider and validate. Retry once with corrective note on schema failure.
        Returns (validated_dict | None, required_retry, ai_available).
        """
        try:
            raw = await self._ai.generate(prompt)
            result = self._validator.validate(raw, changed_files)
            if result.is_valid:
                return result.parsed, False, True

            # First attempt failed schema validation — retry once
            logger.warning("AI validation failed on first attempt: %s", result.violations[:3])
            corrective_prompt = (
                prompt
                + "\n\nIMPORTANT: Your previous response did not match the required JSON schema. "
                "Respond ONLY with the valid JSON object. Issues: "
                + "; ".join(result.violations[:3])
            )
            raw2 = await self._ai.generate(corrective_prompt)
            result2 = self._validator.validate(raw2, changed_files)
            if result2.is_valid:
                return result2.parsed, True, True

            logger.error("AI validation failed after retry. Degraded mode.")
            return None, True, False

        except Exception as exc:
            logger.error("AI Provider error: %s. Falling back to deterministic-only.", exc)
            return None, False, False

    def _build_normalized_pr_data(self, pr_data: PRData) -> NormalizedPRData:
        return NormalizedPRData(
            repo_owner=pr_data.repo_owner,
            repo_name=pr_data.repo_name,
            pr_number=pr_data.pr_number,
            pr_title=pr_data.pr_title,
            author_username=pr_data.author_username,
            base_branch=pr_data.base_branch,
            head_branch=pr_data.head_branch,
            commit_sha=pr_data.commit_sha,
            commit_messages=pr_data.commit_messages,
            changed_files=pr_data.changed_files,
            diff_text=pr_data.diff_text,
        )

    async def _persist_result(
        self,
        db: AsyncSession,
        pull_request: PullRequest,
        commit_sha: str,
        pr_data: PRData,
        validated_ai: dict | None,
        risk_result: RiskResult,
        risk_confidence: float,
        reviewer_result: ReviewerRecommendationResult,
        checklist_result: ChecklistResult,
        triggered_by: str,
        status: str,
    ) -> PullRequestAnalysis:
        """
        Persist the full analysis result atomically.
        One transaction — either everything is written or nothing is.
        """
        # Main analysis record
        analysis = PullRequestAnalysis(
            pull_request_id=pull_request.id,
            commit_sha=commit_sha,
            status=status,
            summary=validated_ai.get("summary") if validated_ai else None,
            checklist_is_fallback_default=checklist_result.is_fallback,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            model_name=MODEL_NAME,
            triggered_by=triggered_by,
        )
        db.add(analysis)
        await db.flush()  # Get the analysis.id before adding children

        # Risk assessment (1:1)
        risk = RiskAssessment(
            analysis_id=analysis.id,
            risk_tier=risk_result.risk_tier,
            deterministic_score=risk_result.deterministic_score,
            ai_risk_signal=risk_result.ai_risk_signal,
            rationale=risk_result.rationale,
            source=risk_result.source,
            confidence_score=risk_confidence,
        )
        db.add(risk)
        await db.flush()  # Assign risk.id so it can be returned in AnalysisResult

        # Review suggestions (1:many)
        if validated_ai and validated_ai.get("review_suggestions"):
            for i, suggestion in enumerate(validated_ai["review_suggestions"]):
                db.add(
                    ReviewSuggestion(
                        analysis_id=analysis.id,
                        focus_area=suggestion.get("focus_area", ""),
                        category=suggestion.get("category"),
                        display_order=i,
                    )
                )

        # Reviewer recommendation (0 or 1+ rows)
        if reviewer_result.has_suggestion:
            db.add(
                ReviewerRecommendation(
                    analysis_id=analysis.id,
                    recommended_github_username=reviewer_result.recommended_username,
                    reason=reviewer_result.reason,
                    rank=1,
                    confidence_score=reviewer_result.confidence_score or 50.0,
                )
            )
            for shortlisted in reviewer_result.shortlist:
                db.add(
                    ReviewerRecommendation(
                        analysis_id=analysis.id,
                        recommended_github_username=shortlisted["github_username"],
                        reason=shortlisted["reason"],
                        rank=shortlisted["rank"],
                        confidence_score=shortlisted["confidence_score"],
                    )
                )

        # Checklist items (0 or many rows)
        for item in checklist_result.items:
            db.add(
                ChecklistItem(
                    analysis_id=analysis.id,
                    category=item.category,
                    confidence_score=item.confidence_score,
                    trigger_source=item.trigger_source,
                )
            )

        await db.flush()

        # Reload with relationships for the return value
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(PullRequestAnalysis)
            .where(PullRequestAnalysis.id == analysis.id)
            .options(
                selectinload(PullRequestAnalysis.risk_assessment),
                selectinload(PullRequestAnalysis.review_suggestions),
                selectinload(PullRequestAnalysis.reviewer_recommendations),
                selectinload(PullRequestAnalysis.checklist_items),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one()
