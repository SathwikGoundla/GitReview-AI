"""
GitReview AI — AI Review Checklist Generator

Generates a PR-specific checklist by merging:
  1. Deterministic rule triggers (fast, auditable)
  2. AI-judged relevant dimensions (semantic understanding)

From LLD Part K / SRS FR-6:
  - Only dimensions from the allowed fixed category set may appear
  - Malformed AI output triggers the baseline fallback checklist
  - trigger_source tracks whether the item came from deterministic, ai, or both
  - No duplicate categories: if deterministic and AI both flag the same category,
    one item is written with trigger_source='both'

LLD Part B.6: ChecklistGenerator — pure rule application, no persistence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ALLOWED_CATEGORIES = {
    "security",
    "performance",
    "exception_handling",
    "null_handling",
    "logging",
    "testing",
    "documentation",
    "dependencies",
    "database_changes",
}

# Baseline fallback when AI output is invalid (SRS FR-6 failure mode)
BASELINE_FALLBACK_CATEGORIES = {"security", "testing"}


@dataclass
class ChecklistItemResult:
    """One checklist item ready for DB persistence."""

    category: str
    confidence_score: float  # 0–100
    trigger_source: str  # deterministic | ai | both
    is_relevant: bool = True


@dataclass
class ChecklistResult:
    """Full checklist generation result."""

    items: list[ChecklistItemResult]
    is_fallback: bool = False


class ChecklistGenerator:
    """
    Applies deterministic trigger rules and AI-judged dimensions.
    Pure rule application — no network I/O, no DB access.
    """

    def generate_checklist(
        self,
        changed_files: list[str],
        ai_checklist_signal: list[dict] | None,
    ) -> ChecklistResult:
        """
        Generate the PR-specific checklist.

        Args:
            changed_files: File paths changed in the PR.
            ai_checklist_signal: Parsed checklist from validated AI response,
                                 or None if AI was unavailable.
                                 Each item: {category, relevant, self_reported_confidence, reason}

        Returns:
            ChecklistResult with items and fallback flag.
        """
        deterministic = self._apply_deterministic_rules(changed_files)

        if ai_checklist_signal is None:
            # AI unavailable — fallback to baseline + deterministic
            return self._build_fallback(deterministic, changed_files)

        ai_items = self._parse_ai_signal(ai_checklist_signal)
        if ai_items is None:
            # Malformed AI output — fallback
            return self._build_fallback(deterministic, changed_files)

        return self._merge(deterministic, ai_items)

    # ── Private ──────────────────────────────────────────────────────────────────

    def _apply_deterministic_rules(self, changed_files: list[str]) -> dict[str, float]:
        """
        Apply deterministic trigger rules. Returns {category: confidence_score}.
        From LLD Part K deterministic rule contribution.
        """
        triggered: dict[str, float] = {}

        has_test_changes = any(_TEST_RE.search(f) for f in changed_files)
        has_source_changes = any(
            _SOURCE_RE.search(f) and not _TEST_RE.search(f) for f in changed_files
        )

        # Rule: source changed without test changes → testing
        if has_source_changes and not has_test_changes:
            triggered["testing"] = 90.0

        # Rule: DB migration file present → database_changes
        if any(_MIGRATION_RE.search(f) for f in changed_files):
            triggered["database_changes"] = 95.0

        # Rule: dependency manifest modified → dependencies
        if any(_DEPENDENCY_RE.search(f) for f in changed_files):
            triggered["dependencies"] = 90.0

        # Rule: security/auth path touched → security
        if any(_SECURITY_PATH_RE.search(f) for f in changed_files):
            triggered["security"] = 95.0

        # Rule: public interface change without docs → documentation
        if any(_INTERFACE_RE.search(f) for f in changed_files) and not any(
            _DOCS_RE.search(f) for f in changed_files
        ):
            triggered["documentation"] = 70.0

        return triggered

    def _parse_ai_signal(self, ai_checklist: list[dict]) -> dict[str, tuple[bool, float]] | None:
        """
        Parse AI checklist signal. Returns {category: (relevant, confidence)} or None on error.
        """
        result: dict[str, tuple[bool, float]] = {}
        try:
            if not isinstance(ai_checklist, list):
                return None
            for item in ai_checklist:
                if not isinstance(item, dict):
                    return None
                cat = item.get("category", "")
                if cat not in ALLOWED_CATEGORIES:
                    # Invalid category — not a hard failure but skip this item
                    continue
                relevant = bool(item.get("relevant", False))
                conf = float(item.get("self_reported_confidence", 50))
                conf = max(0.0, min(100.0, conf))
                result[cat] = (relevant, conf)
        except (TypeError, KeyError, ValueError, AttributeError):
            return None
        return result

    def _merge(
        self,
        deterministic: dict[str, float],
        ai_items: dict[str, tuple[bool, float]],
    ) -> ChecklistResult:
        """
        Merge deterministic triggers and AI-judged items.
        When both fire for the same category: trigger_source='both'.
        """
        merged: dict[str, ChecklistItemResult] = {}

        # Add all deterministic triggers (always included regardless of AI)
        for cat, conf in deterministic.items():
            merged[cat] = ChecklistItemResult(
                category=cat,
                confidence_score=conf,
                trigger_source="deterministic",
                is_relevant=True,
            )

        # Add AI-judged items
        for cat, (relevant, conf) in ai_items.items():
            if not relevant:
                continue  # AI says not relevant — skip unless deterministic also fires
            if cat in merged:
                # Both deterministic and AI fired → 'both', take higher confidence
                merged[cat] = ChecklistItemResult(
                    category=cat,
                    confidence_score=max(merged[cat].confidence_score, conf),
                    trigger_source="both",
                    is_relevant=True,
                )
            else:
                merged[cat] = ChecklistItemResult(
                    category=cat,
                    confidence_score=conf,
                    trigger_source="ai",
                    is_relevant=True,
                )

        return ChecklistResult(items=list(merged.values()), is_fallback=False)

    def _build_fallback(
        self, deterministic: dict[str, float], changed_files: list[str] | None = None
    ) -> ChecklistResult:
        """
        Build the baseline fallback checklist.
        Includes deterministic triggers + the baseline set, flagged as fallback.

        Baseline items are only added when deterministic rules have NOT already
        determined they are not applicable. Specifically: 'testing' is a baseline
        item but is NOT added when test files are present in the PR (because the
        deterministic rule intentionally skips it in that case).
        """
        items: dict[str, ChecklistItemResult] = {}

        # Determine which baseline items to suppress based on file context
        suppressed_baseline: set[str] = set()
        if changed_files is not None:
            has_test_changes = any(_TEST_RE.search(f) for f in changed_files)
            if has_test_changes:
                suppressed_baseline.add("testing")

        for cat in BASELINE_FALLBACK_CATEGORIES:
            if cat in suppressed_baseline:
                continue
            items[cat] = ChecklistItemResult(
                category=cat,
                confidence_score=50.0,  # Conservative — no AI signal
                trigger_source="deterministic",
                is_relevant=True,
            )

        for cat, conf in deterministic.items():
            items[cat] = ChecklistItemResult(
                category=cat,
                confidence_score=conf,
                trigger_source="deterministic",
                is_relevant=True,
            )

        return ChecklistResult(items=list(items.values()), is_fallback=True)


# ── File pattern regexes ──────────────────────────────────────────────────────

_TEST_RE = re.compile(r"(test_|_test\.|\.test\.|\.spec\.|/tests?/|/spec/)", re.I)
_SOURCE_RE = re.compile(r"\.(py|js|ts|jsx|tsx|java|go|rb|rs|cpp|c|cs|swift|kt)$", re.I)
_MIGRATION_RE = re.compile(
    r"(migrations?/|alembic/versions/|db/migrate/|\d+_\w+\.(sql|py|rb)$)", re.I
)
_DEPENDENCY_RE = re.compile(
    r"(package\.json|requirements\.txt|Pipfile|poetry\.lock|go\.mod|Gemfile|pom\.xml)", re.I
)
_SECURITY_PATH_RE = re.compile(
    r"/(auth|authentication|authorization|security|crypto|payment|secrets|admin)/", re.I
)
_INTERFACE_RE = re.compile(r"\.(py|js|ts|java|go|rb|rs)$", re.I)
_DOCS_RE = re.compile(r"\.(md|rst|txt|adoc|html)$|/docs?/", re.I)
