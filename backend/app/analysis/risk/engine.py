"""
GitReview AI — Hybrid Risk Engine

Combines deterministic engineering signals with the AI-derived risk signal.

From HLD Section 6 / LLD Part H:
  - Deterministic signals computed without AI
  - AI signal is advisory only — cannot reduce a deterministic evidence-based tier
  - If AI unavailable: deterministic-only tier, labeled source='deterministic_only'
  - Tier escalation favors caution (AI can raise, not lower)

The AI does NOT have unilateral authority to set the final tier.
The deterministic engine does not ignore semantic context the AI can evaluate.

LLD Part B.6: RiskEngine — no AI calls, consumes already-validated AI signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import get_settings

RISK_TIERS = ["low", "medium", "high", "critical"]

# Deterministic signal point values
_POINTS = {
    "sensitive_path": 30,
    "no_tests_with_source": 20,
    "db_migration": 25,
    "dependency_manifest": 15,
    "config_infra": 15,
    "large_diff_medium": 10,
    "large_diff_high": 25,
    "large_diff_critical": 40,
    "many_files": 10,
}


@dataclass
class DeterministicSignals:
    """Signals extractable from diff metadata without AI."""

    lines_changed: int = 0
    files_changed: int = 0
    sensitive_paths_touched: list[str] = field(default_factory=list)
    has_test_changes: bool = False
    has_source_changes: bool = False
    has_db_migration: bool = False
    has_dependency_manifest: bool = False
    has_config_or_infra: bool = False


@dataclass
class RiskResult:
    """Final risk assessment result."""

    risk_tier: str  # low|medium|high|critical
    deterministic_score: float
    ai_risk_signal: str | None  # AI's proposed tier (advisory)
    rationale: dict  # JSON-serializable structured factors
    source: str  # deterministic_only|hybrid


# Dependency manifest file patterns
_DEPENDENCY_FILES = re.compile(
    r"(package\.json|package-lock\.json|requirements\.txt|Pipfile|Pipfile\.lock|"
    r"poetry\.lock|go\.mod|go\.sum|Gemfile|Gemfile\.lock|pom\.xml|build\.gradle|"
    r"composer\.json|composer\.lock|Cargo\.toml|Cargo\.lock)",
    re.IGNORECASE,
)

# Config/infra file patterns
_INFRA_FILES = re.compile(
    r"(\.env|\.env\.\w+|Dockerfile|docker-compose|\.github/workflows/|"
    r"\.gitlab-ci\.yml|Makefile|ansible|terraform|kubernetes|k8s|helm|"
    r"nginx\.conf|apache\.conf|supervisord\.conf)",
    re.IGNORECASE,
)

# DB migration patterns
_MIGRATION_FILES = re.compile(
    r"(migrations?/|alembic/versions/|db/migrate/|database/migrations?/|"
    r"\d+_\w+\.(sql|py|rb|js|ts)$)",
    re.IGNORECASE,
)

# Test file patterns
_TEST_FILES = re.compile(
    r"(test_|_test\.|\.test\.|\.spec\.|/tests?/|/spec/)",
    re.IGNORECASE,
)

# Source file patterns (non-test code)
_SOURCE_FILES = re.compile(
    r"\.(py|js|ts|jsx|tsx|java|go|rb|rs|cpp|c|cs|swift|kt)$",
    re.IGNORECASE,
)


class RiskEngine:
    """
    Computes the hybrid risk tier from deterministic and AI-derived signals.

    Design invariant: the AI signal is advisory.
    - If AI proposes a HIGHER tier → escalate (favor caution).
    - If AI proposes a LOWER tier → keep deterministic base (AI cannot talk down a hard signal).
    - If AI unavailable → deterministic-only, labeled explicitly.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def compute_deterministic_signals(
        self,
        changed_files: list[str],
        lines_added: int,
        lines_removed: int,
    ) -> DeterministicSignals:
        """Extract deterministic signals from diff metadata."""
        signals = DeterministicSignals(
            lines_changed=lines_added + lines_removed,
            files_changed=len(changed_files),
        )

        for path in changed_files:
            # Sensitive path detection
            for pattern in self._settings.sensitive_path_patterns:
                if pattern.lower() in path.lower():
                    signals.sensitive_paths_touched.append(path)
                    break

            # Test vs source
            if _TEST_FILES.search(path):
                signals.has_test_changes = True
            elif _SOURCE_FILES.search(path):
                signals.has_source_changes = True

            # DB migration
            if _MIGRATION_FILES.search(path):
                signals.has_db_migration = True

            # Dependency manifest
            if _DEPENDENCY_FILES.search(path):
                signals.has_dependency_manifest = True

            # Config/infra
            if _INFRA_FILES.search(path):
                signals.has_config_or_infra = True

        return signals

    def assess_risk(
        self,
        signals: DeterministicSignals,
        ai_risk_signal: str | None,
    ) -> RiskResult:
        """
        Combine deterministic signals with the AI-derived signal into a final risk tier.

        Args:
            signals: Deterministic signals from diff metadata.
            ai_risk_signal: AI's proposed tier (from validated AI response), or None.

        Returns:
            RiskResult with the final tier, score, rationale, and source label.
        """
        score, factors = self._score_deterministic(signals)
        base_tier = self._score_to_tier(score)
        final_tier = base_tier
        source = "deterministic_only"

        if ai_risk_signal and ai_risk_signal in RISK_TIERS:
            source = "hybrid"
            ai_idx = RISK_TIERS.index(ai_risk_signal)
            base_idx = RISK_TIERS.index(base_tier)

            if ai_idx > base_idx:
                # AI proposes higher → escalate (caution wins)
                final_tier = ai_risk_signal
                factors.append(
                    {
                        "factor": "AI semantic escalation",
                        "source": "ai",
                        "detail": (
                            f"AI identified risk factors elevating tier from "
                            f"{base_tier} to {ai_risk_signal}."
                        ),
                    }
                )
            elif ai_idx < base_idx:
                # AI proposes lower → keep deterministic (AI cannot override hard signals)
                factors.append(
                    {
                        "factor": "AI signal disagreement (deterministic override)",
                        "source": "ai",
                        "detail": (
                            f"AI proposed {ai_risk_signal} but deterministic signals require "
                            f"{base_tier}. Deterministic tier retained."
                        ),
                    }
                )
            else:
                # Agreement → confirm
                factors.append(
                    {
                        "factor": "AI signal agreement",
                        "source": "ai",
                        "detail": f"AI independently agrees with {final_tier} tier.",
                    }
                )

        return RiskResult(
            risk_tier=final_tier,
            deterministic_score=score,
            ai_risk_signal=ai_risk_signal,
            rationale={"factors": factors},
            source=source,
        )

    # ── Private ──────────────────────────────────────────────────────────────────

    def _score_deterministic(self, signals: DeterministicSignals) -> tuple[float, list[dict]]:
        """Compute a deterministic score and collect factor explanations."""
        score = 0.0
        factors: list[dict] = []

        if signals.sensitive_paths_touched:
            score += _POINTS["sensitive_path"]
            factors.append(
                {
                    "factor": "Sensitive path touched",
                    "source": "deterministic",
                    "detail": (
                        f"Files in sensitive paths: "
                        f"{', '.join(signals.sensitive_paths_touched[:5])}"
                    ),
                }
            )

        if signals.has_source_changes and not signals.has_test_changes:
            score += _POINTS["no_tests_with_source"]
            factors.append(
                {
                    "factor": "Source changes without test changes",
                    "source": "deterministic",
                    "detail": "Production source files modified with no corresponding test file changes.",
                }
            )

        if signals.has_db_migration:
            score += _POINTS["db_migration"]
            factors.append(
                {
                    "factor": "Database migration present",
                    "source": "deterministic",
                    "detail": "A database migration file was detected in the changed files.",
                }
            )

        if signals.has_dependency_manifest:
            score += _POINTS["dependency_manifest"]
            factors.append(
                {
                    "factor": "Dependency manifest modified",
                    "source": "deterministic",
                    "detail": "A dependency manifest (package.json, requirements.txt, etc.) was modified.",
                }
            )

        if signals.has_config_or_infra:
            score += _POINTS["config_infra"]
            factors.append(
                {
                    "factor": "Configuration or infrastructure file changed",
                    "source": "deterministic",
                    "detail": "A config, CI, or infrastructure file was modified.",
                }
            )

        # Diff size
        settings = self._settings
        if signals.lines_changed >= settings.risk_size_critical_lines:
            score += _POINTS["large_diff_critical"]
            factors.append(
                {
                    "factor": "Very large diff",
                    "source": "deterministic",
                    "detail": f"{signals.lines_changed} lines changed (critical threshold: "
                    f"{settings.risk_size_critical_lines}).",
                }
            )
        elif signals.lines_changed >= settings.risk_size_high_lines:
            score += _POINTS["large_diff_high"]
            factors.append(
                {
                    "factor": "Large diff",
                    "source": "deterministic",
                    "detail": f"{signals.lines_changed} lines changed.",
                }
            )
        elif signals.lines_changed >= settings.risk_size_medium_lines:
            score += _POINTS["large_diff_medium"]
            factors.append(
                {
                    "factor": "Medium diff",
                    "source": "deterministic",
                    "detail": f"{signals.lines_changed} lines changed.",
                }
            )

        if signals.files_changed > 20:
            score += _POINTS["many_files"]
            factors.append(
                {
                    "factor": "Many files changed",
                    "source": "deterministic",
                    "detail": f"{signals.files_changed} files changed.",
                }
            )

        return score, factors

    def _score_to_tier(self, score: float) -> str:
        """Map a deterministic score to a risk tier."""
        if score >= 60:
            return "critical"
        if score >= 35:
            return "high"
        if score >= 15:
            return "medium"
        return "low"
