"""
GitReview AI — AI Output Validation Module

Validates raw Gemini output against the required internal schema.
LLD Part A.10: Rejects any response with missing, malformed, or out-of-range
fields, or references to files/people not present in the source data.

This module has no network I/O and no side effects — pure validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

ALLOWED_RISK_TIERS = {"low", "medium", "high", "critical"}
ALLOWED_CHECKLIST_CATEGORIES = {
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
REQUIRED_CHECKLIST_CATEGORIES = ALLOWED_CHECKLIST_CATEGORIES.copy()


@dataclass
class ValidationResult:
    """Result of validating raw AI output."""

    is_valid: bool
    parsed: dict | None = None
    violations: list[str] = field(default_factory=list)


class AnalysisResponseValidator:
    """
    Validates the AI Provider's raw response against the internal schema.
    Pure validation — no retries, no network calls, no DB access.
    The Orchestrator triggers a retry on ValidationFailure.
    """

    def validate(
        self,
        raw_response: str,
        changed_files: list[str] | None = None,
    ) -> ValidationResult:
        """
        Parse and validate the raw AI response.

        Args:
            raw_response: Raw string from the AI Provider.
            changed_files: Files present in the PR — used to check hallucinated references.

        Returns:
            ValidationResult with is_valid=True and parsed dict on success,
            or is_valid=False with violation list on failure.
        """
        violations: list[str] = []

        # 1. Extract JSON (model may wrap in markdown fences)
        parsed = self._extract_json(raw_response)
        if parsed is None:
            return ValidationResult(
                is_valid=False,
                violations=["Response is not valid JSON or JSON could not be extracted."],
            )

        # 2. Required top-level fields
        required_fields = {
            "summary",
            "risk_tier",
            "risk_rationale",
            "ai_risk_signal",
            "self_reported_confidence",
            "review_suggestions",
            "reviewer_signals",
            "checklist",
        }
        missing = required_fields - set(parsed.keys())
        if missing:
            violations.append(f"Missing required fields: {sorted(missing)}")

        # 3. risk_tier enum
        risk_tier = parsed.get("risk_tier", "")
        if risk_tier not in ALLOWED_RISK_TIERS:
            violations.append(
                f"risk_tier '{risk_tier}' is not one of {sorted(ALLOWED_RISK_TIERS)}."
            )

        # 4. ai_risk_signal enum
        ai_signal = parsed.get("ai_risk_signal", "")
        if ai_signal not in ALLOWED_RISK_TIERS:
            violations.append(
                f"ai_risk_signal '{ai_signal}' is not one of {sorted(ALLOWED_RISK_TIERS)}."
            )

        # 5. self_reported_confidence range
        conf = parsed.get("self_reported_confidence")
        if not isinstance(conf, int) or not (0 <= conf <= 100):
            violations.append(f"self_reported_confidence must be an integer 0-100, got: {conf!r}.")

        # 6. risk_rationale structure
        rationale = parsed.get("risk_rationale", {})
        if not isinstance(rationale, dict) or "factors" not in rationale:
            violations.append("risk_rationale must be a dict with a 'factors' list.")
        else:
            for i, factor in enumerate(rationale.get("factors", [])):
                if not isinstance(factor, dict):
                    violations.append(f"risk_rationale.factors[{i}] must be a dict.")
                    continue
                if "factor" not in factor or "source" not in factor or "detail" not in factor:
                    violations.append(
                        f"risk_rationale.factors[{i}] missing required keys "
                        "(factor, source, detail)."
                    )
                if factor.get("source") not in ("deterministic", "ai"):
                    violations.append(
                        f"risk_rationale.factors[{i}].source must be 'deterministic' or 'ai'."
                    )

        # 7. review_suggestions
        suggestions = parsed.get("review_suggestions", [])
        if not isinstance(suggestions, list):
            violations.append("review_suggestions must be a list.")
        else:
            for i, s in enumerate(suggestions):
                if not isinstance(s, dict) or "focus_area" not in s:
                    violations.append(f"review_suggestions[{i}] must have 'focus_area' field.")

        # 8. checklist — all 9 allowed categories must appear
        checklist = parsed.get("checklist", [])
        if not isinstance(checklist, list):
            violations.append("checklist must be a list.")
        else:
            present_categories: set[str] = set()
            for i, item in enumerate(checklist):
                if not isinstance(item, dict):
                    violations.append(f"checklist[{i}] must be a dict.")
                    continue
                cat = item.get("category", "")
                if cat not in ALLOWED_CHECKLIST_CATEGORIES:
                    violations.append(f"checklist[{i}].category '{cat}' is not in the allowed set.")
                else:
                    present_categories.add(cat)
                conf_item = item.get("self_reported_confidence")
                if not isinstance(conf_item, int) or not (0 <= conf_item <= 100):
                    violations.append(f"checklist[{i}].self_reported_confidence must be int 0-100.")
                if "relevant" not in item:
                    violations.append(f"checklist[{i}] missing 'relevant' boolean.")

            missing_cats = REQUIRED_CHECKLIST_CATEGORIES - present_categories
            if missing_cats:
                violations.append(
                    f"checklist is missing required categories: {sorted(missing_cats)}."
                )

        # 9. Hallucination check: no file references not in the PR
        if changed_files is not None:
            changed_files_set = set(changed_files)
            for i, s in enumerate(parsed.get("review_suggestions", [])):
                focus = s.get("focus_area", "")
                self._check_hallucinated_file_refs(
                    focus, changed_files_set, violations, f"review_suggestions[{i}]"
                )

        if violations:
            return ValidationResult(is_valid=False, violations=violations)

        return ValidationResult(is_valid=True, parsed=parsed)

    def describe_violations(
        self, raw_response: str, changed_files: list[str] | None = None
    ) -> list[str]:
        """Return violations without raising, for logging purposes."""
        result = self.validate(raw_response, changed_files)
        return result.violations

    # ── Private ─────────────────────────────────────────────────────────────────

    def _extract_json(self, raw: str) -> dict | None:
        """
        Extract JSON from raw response, handling markdown code fences.
        The model may wrap JSON in ```json ... ``` blocks.
        """
        # Try direct parse first
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try stripping markdown fences
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding any JSON object in the response
        brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _check_hallucinated_file_refs(
        self,
        text: str,
        valid_files: set[str],
        violations: list[str],
        location: str,
    ) -> None:
        """
        Check if a text field references specific file paths that don't exist in the PR.
        Only flags references that look like file paths (contain / or .) and aren't in
        the changed files set.
        """
        # Extract things that look like file paths
        candidates = re.findall(r"[\w/.-]+\.[a-zA-Z]{1,6}", text)
        for candidate in candidates:
            if "/" in candidate and candidate not in valid_files:
                violations.append(
                    f"{location}: possible hallucinated file reference '{candidate}' "
                    f"not found in PR's changed files."
                )
