"""
GitReview AI — Confidence Scoring Module

Computes a 0–100% confidence indicator per prediction.

From HLD Section 5 (Architectural Note):
  Raw LLM token probabilities are NOT a reliable confidence measure.
  GitReview AI does NOT use raw token probabilities.

Hybrid method (LLD Part I):
  1. Model self-report — weak input, normalized from AI's self_reported_confidence
  2. Agreement signal — whether AI tier matched deterministic base tier
  3. Evidence completeness — whether supporting data was fully available
  4. Validation penalty — if AI output required a retry (retry lowers confidence)
  5. Historical calibration — helpful/unhelpful ratio from feedback
     (only applied once minimum sample threshold is reached)

Output is strictly 0–100.
Cold-start cap: 85 (never display maximal certainty before real-world validation).

LLD Part B.6: ConfidenceCalculator — stateless computation given inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings

SCORING_FUNCTION_VERSION = "v1.0"


@dataclass
class CalibrationData:
    """Feedback calibration aggregate from confidence_calibration table."""

    prediction_type: str
    helpful_count: int
    unhelpful_count: int

    @property
    def total(self) -> int:
        return self.helpful_count + self.unhelpful_count

    @property
    def helpful_ratio(self) -> float:
        if self.total == 0:
            return 0.5  # neutral prior
        return self.helpful_count / self.total


@dataclass
class ConfidenceInputs:
    """All inputs for computing confidence for one prediction instance."""

    prediction_type: str  # risk_tier | reviewer_recommendation | checklist_item
    ai_self_report: int  # 0–100 from the AI's self_reported_confidence
    ai_tier: str | None  # AI's proposed tier (for agreement signal)
    deterministic_tier: str | None  # Deterministic base tier (for agreement signal)
    required_retry: bool  # Whether the AI output needed a retry
    evidence_complete: bool  # Whether supporting data was fully available
    calibration: CalibrationData | None  # Historical feedback aggregate, or None


class ConfidenceCalculator:
    """
    Implements the hybrid scoring function (LLD Part I).
    Stateless computation — holds no data of its own.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self.scoring_function_version = SCORING_FUNCTION_VERSION

    def compute_confidence(self, inputs: ConfidenceInputs) -> float:
        """
        Compute a confidence percentage (0–100) for one prediction instance.

        The formula is intentionally transparent and versioned:
          base = weighted_avg(self_report, agreement_bonus, evidence_score)
          penalty for retry
          calibration adjustment when sufficient feedback exists
          cold-start cap at 85 when calibration data insufficient

        Returns:
            float in [0, 100]
        """
        settings = self._settings

        # --- Signal 1: Model self-report (weak — normalized to [0, 100])
        self_report_score = float(max(0, min(100, inputs.ai_self_report)))
        # Weight the self-report at 30% — it's a weak, biased signal
        weighted_self_report = self_report_score * 0.30

        # --- Signal 2: Agreement with deterministic signals (40% weight)
        agreement_score = self._agreement_score(inputs.ai_tier, inputs.deterministic_tier)
        weighted_agreement = agreement_score * 0.40

        # --- Signal 3: Evidence completeness (30% weight)
        evidence_score = 80.0 if inputs.evidence_complete else 40.0
        weighted_evidence = evidence_score * 0.30

        # --- Base score
        base = weighted_self_report + weighted_agreement + weighted_evidence

        # --- Retry penalty (signals uncertain AI output)
        if inputs.required_retry:
            base = base * 0.80  # 20% penalty

        # --- Cold-start cap (before calibration has enough data)
        min_samples = settings.confidence_min_feedback_samples
        cold_start_cap = float(settings.confidence_cold_start_cap)

        if inputs.calibration is None or inputs.calibration.total < min_samples:
            # Not enough feedback to calibrate — apply cold-start cap
            result = min(base, cold_start_cap)
        else:
            # Enough feedback — blend in calibration adjustment
            calibration_adjustment = self._calibration_adjustment(inputs.calibration)
            result = base + calibration_adjustment

        # --- Strictly bound to [0, 100]
        return float(max(0.0, min(100.0, result)))

    def get_confidence_band(self, score: float) -> str:
        """
        Map a confidence score to a display band.
        These are display conventions, NOT scientific thresholds (LLD Part I).
        """
        if score >= 80:
            return "high"
        if score >= 50:
            return "moderate"
        return "low"

    # ── Private ──────────────────────────────────────────────────────────────────

    def _agreement_score(self, ai_tier: str | None, deterministic_tier: str | None) -> float:
        """
        Score based on whether AI and deterministic signals agree.
        Agreement raises confidence; disagreement lowers it.
        """
        if ai_tier is None or deterministic_tier is None:
            # One signal missing — use neutral score
            return 50.0

        if ai_tier == deterministic_tier:
            return 90.0  # Strong agreement
        # Adjacent tiers (e.g., medium vs high) = partial agreement
        tiers = ["low", "medium", "high", "critical"]
        try:
            ai_idx = tiers.index(ai_tier)
            det_idx = tiers.index(deterministic_tier)
            diff = abs(ai_idx - det_idx)
            if diff == 1:
                return 60.0  # Adjacent tier — some disagreement
            return 30.0  # Far disagreement
        except ValueError:
            return 50.0

    def _calibration_adjustment(self, calibration: CalibrationData) -> float:
        """
        Compute a calibration adjustment based on historical feedback.
        Helpful ratio > 0.7 → small positive boost.
        Helpful ratio < 0.3 → penalty.
        Returns a value in approximately [-15, +10].
        """
        ratio = calibration.helpful_ratio
        if ratio >= 0.7:
            return 10.0 * (ratio - 0.5) / 0.5  # up to +10
        if ratio <= 0.3:
            return -15.0 * (0.5 - ratio) / 0.5  # up to -15
        return 0.0  # Neutral range — no adjustment
