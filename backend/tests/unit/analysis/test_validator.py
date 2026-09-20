"""Unit tests for app.analysis.validation.validator."""

from __future__ import annotations

import json
import os

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")

ALLOWED_CATEGORIES = [
    "security",
    "performance",
    "exception_handling",
    "null_handling",
    "logging",
    "testing",
    "documentation",
    "dependencies",
    "database_changes",
]


def _make_valid_response(**overrides) -> str:
    """Build a minimal valid AI response JSON string."""
    checklist = [
        {
            "category": cat,
            "relevant": True,
            "self_reported_confidence": 75,
            "reason": f"Test reason for {cat}",
        }
        for cat in ALLOWED_CATEGORIES
    ]
    base = {
        "summary": "This PR adds OAuth login support.",
        "risk_tier": "medium",
        "risk_rationale": {
            "factors": [
                {
                    "factor": "Auth path touched",
                    "source": "deterministic",
                    "detail": "auth/login.py",
                }
            ]
        },
        "ai_risk_signal": "medium",
        "self_reported_confidence": 72,
        "review_suggestions": [
            {"focus_area": "Verify null handling in token refresh", "category": "null_handling"},
            {"focus_area": "Check error paths in OAuth callback", "category": "exception_handling"},
        ],
        "reviewer_signals": {
            "key_files": ["auth/login.py"],
            "domain_keywords": ["oauth", "authentication"],
        },
        "checklist": checklist,
    }
    base.update(overrides)
    return json.dumps(base)


class TestValidResponseAccepted:
    def setup_method(self):
        from app.analysis.validation.validator import AnalysisResponseValidator

        self.v = AnalysisResponseValidator()

    def test_valid_response_passes(self):
        result = self.v.validate(_make_valid_response())
        assert result.is_valid is True
        assert result.parsed is not None
        assert result.violations == []

    def test_valid_response_with_markdown_fence(self):
        inner = _make_valid_response()
        fenced = f"```json\n{inner}\n```"
        result = self.v.validate(fenced)
        assert result.is_valid is True

    def test_all_risk_tiers_accepted(self):
        for tier in ("low", "medium", "high", "critical"):
            resp = _make_valid_response(risk_tier=tier, ai_risk_signal=tier)
            result = self.v.validate(resp)
            assert result.is_valid is True, f"Tier '{tier}' should be valid: {result.violations}"


class TestMissingFields:
    def setup_method(self):
        from app.analysis.validation.validator import AnalysisResponseValidator

        self.v = AnalysisResponseValidator()

    def test_missing_summary(self):
        data = json.loads(_make_valid_response())
        del data["summary"]
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False
        assert any("summary" in v for v in result.violations)

    def test_missing_risk_tier(self):
        data = json.loads(_make_valid_response())
        del data["risk_tier"]
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_missing_checklist(self):
        data = json.loads(_make_valid_response())
        del data["checklist"]
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_missing_review_suggestions(self):
        data = json.loads(_make_valid_response())
        del data["review_suggestions"]
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_missing_self_reported_confidence(self):
        data = json.loads(_make_valid_response())
        del data["self_reported_confidence"]
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False


class TestInvalidFieldValues:
    def setup_method(self):
        from app.analysis.validation.validator import AnalysisResponseValidator

        self.v = AnalysisResponseValidator()

    def test_invalid_risk_tier(self):
        result = self.v.validate(_make_valid_response(risk_tier="extreme"))
        assert result.is_valid is False
        assert any("risk_tier" in v for v in result.violations)

    def test_confidence_out_of_range_high(self):
        result = self.v.validate(_make_valid_response(self_reported_confidence=150))
        assert result.is_valid is False

    def test_confidence_out_of_range_low(self):
        result = self.v.validate(_make_valid_response(self_reported_confidence=-5))
        assert result.is_valid is False

    def test_confidence_not_integer(self):
        result = self.v.validate(_make_valid_response(self_reported_confidence="high"))
        assert result.is_valid is False

    def test_invalid_checklist_category(self):
        data = json.loads(_make_valid_response())
        data["checklist"][0]["category"] = "INVENTED"
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_checklist_missing_relevant_field(self):
        data = json.loads(_make_valid_response())
        del data["checklist"][0]["relevant"]
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_checklist_item_confidence_out_of_range(self):
        data = json.loads(_make_valid_response())
        data["checklist"][0]["self_reported_confidence"] = 200
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_missing_checklist_category(self):
        """All 9 required categories must appear."""
        data = json.loads(_make_valid_response())
        data["checklist"] = [item for item in data["checklist"] if item["category"] != "security"]
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False
        assert any("security" in v for v in result.violations)

    def test_rationale_missing_factors(self):
        data = json.loads(_make_valid_response())
        data["risk_rationale"] = {"no_factors": True}
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_factor_invalid_source(self):
        data = json.loads(_make_valid_response())
        data["risk_rationale"]["factors"][0]["source"] = "magic"
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False

    def test_invalid_ai_risk_signal(self):
        result = self.v.validate(_make_valid_response(ai_risk_signal="EXTREME"))
        assert result.is_valid is False


class TestEdgeCases:
    def setup_method(self):
        from app.analysis.validation.validator import AnalysisResponseValidator

        self.v = AnalysisResponseValidator()

    def test_empty_string_fails(self):
        result = self.v.validate("")
        assert result.is_valid is False

    def test_plain_text_fails(self):
        result = self.v.validate("This is not JSON at all.")
        assert result.is_valid is False

    def test_empty_json_object_fails(self):
        result = self.v.validate("{}")
        assert result.is_valid is False

    def test_describe_violations_returns_list(self):
        result = self.v.describe_violations("{}")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_valid_response_no_violations(self):
        violations = self.v.describe_violations(_make_valid_response())
        assert violations == []

    def test_suggestion_without_focus_area_flagged(self):
        data = json.loads(_make_valid_response())
        data["review_suggestions"][0] = {"category": "security"}  # missing focus_area
        result = self.v.validate(json.dumps(data))
        assert result.is_valid is False
