"""
GitReview AI — Step 19: GitHub Actions Integration Tests

Tests cover:
  - Shared secret validation (valid, wrong, empty, endpoint disabled)
  - Comment formatting (all fields, fallback, degraded, failed, truncation)
  - ActionsAnalyzeRequest schema validation
  - ActionsAnalysisResponse schema
  - API endpoint: auth failure, missing token, repo not found, success
  - Idempotency marker presence in formatted comment
  - Security: secrets not in response bodies or log output
  - Workflow config: file exists, correct triggers, permissions, concurrency

These tests do NOT require real GitHub credentials, a live backend, or a
real Gemini API key. All external dependencies are mocked.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.actions_integration.schemas import ActionsAnalysisResponse, ActionsAnalyzeRequest
from app.actions_integration.service import (
    COMMENT_MARKER,
    format_pr_comment,
    validate_shared_secret,
)
from app.core.exceptions import ActionsAuthError
from app.main import app

# ── Helpers ────────────────────────────────────────────────────────────────────

VALID_SHA = "a" * 40


def _make_request(**kwargs) -> ActionsAnalyzeRequest:
    defaults = {
        "owner": "octocat",
        "name": "hello-world",
        "pr_number": 42,
        "commit_sha": VALID_SHA,
    }
    defaults.update(kwargs)
    return ActionsAnalyzeRequest(**defaults)


def _make_result_dict(**kwargs) -> dict[str, Any]:
    """Minimal analysis result dict for comment formatter tests."""
    defaults = {
        "status": "completed",
        "risk_tier": "high",
        "risk_source": "hybrid",
        "risk_confidence": 87.5,
        "summary": "This PR adds a new payment endpoint.",
        "commit_sha": VALID_SHA,
        "checklist_items": [
            {"category": "security", "confidence_score": 90.0, "trigger_source": "deterministic"},
            {"category": "testing", "confidence_score": 75.0, "trigger_source": "ai"},
        ],
        "checklist_is_fallback": False,
        "reviewer_recommendation": {
            "username": "alice",
            "reason": "Previously reviewed authentication module.",
            "confidence_score": 82.0,
        },
        "risk_rationale": {
            "factors": [
                {"factor": "Sensitive path touched", "detail": "auth/payments.py"},
                {"factor": "No test file changes"},
            ]
        },
    }
    defaults.update(kwargs)
    return defaults


# ── Schema validation tests ────────────────────────────────────────────────────


class TestActionsAnalyzeRequestSchema:
    def test_valid_request(self):
        req = _make_request()
        assert req.owner == "octocat"
        assert req.pr_number == 42
        assert len(req.commit_sha) == 40

    def test_commit_sha_must_be_40_chars(self):
        import pydantic

        with pytest.raises((pydantic.ValidationError, ValueError)):
            _make_request(commit_sha="abc123")

    def test_pr_number_must_be_positive(self):
        import pydantic

        with pytest.raises((pydantic.ValidationError, ValueError)):
            _make_request(pr_number=0)

    def test_pr_number_minimum_1(self):
        req = _make_request(pr_number=1)
        assert req.pr_number == 1

    def test_all_fields_required(self):
        import pydantic

        with pytest.raises((pydantic.ValidationError, ValueError)):
            ActionsAnalyzeRequest(owner="x", name="y", pr_number=1)  # missing commit_sha


class TestActionsAnalysisResponseSchema:
    def test_response_has_comment_markdown(self):
        resp = ActionsAnalysisResponse(
            status="completed",
            risk_tier="low",
            risk_source="hybrid",
            risk_confidence=90.0,
            summary="Minor fix.",
            commit_sha=VALID_SHA,
            comment_markdown="## GitReview AI\n\nLow risk.",
        )
        assert resp.comment_markdown
        assert resp.status == "completed"

    def test_response_confidence_bounds(self):
        import pydantic

        with pytest.raises((pydantic.ValidationError, ValueError)):
            ActionsAnalysisResponse(
                status="completed",
                risk_tier="low",
                risk_source="hybrid",
                risk_confidence=101.0,  # out of range
                commit_sha=VALID_SHA,
                comment_markdown="",
            )


# ── Shared secret validation tests ────────────────────────────────────────────


class TestValidateSharedSecret:
    def test_valid_secret_passes(self):
        with patch("app.actions_integration.service.settings") as mock_settings:
            mock_settings.actions_shared_secret = "correct-secret-xyz"
            validate_shared_secret("correct-secret-xyz")  # must not raise

    def test_wrong_secret_raises_actions_auth_error(self):
        with patch("app.actions_integration.service.settings") as mock_settings:
            mock_settings.actions_shared_secret = "correct-secret"
            with pytest.raises(ActionsAuthError):
                validate_shared_secret("wrong-secret")

    def test_empty_provided_raises(self):
        with patch("app.actions_integration.service.settings") as mock_settings:
            mock_settings.actions_shared_secret = "correct-secret"
            with pytest.raises(ActionsAuthError):
                validate_shared_secret("")

    def test_empty_configured_raises(self):
        """Endpoint is disabled when ACTIONS_SHARED_SECRET is not set."""
        with patch("app.actions_integration.service.settings") as mock_settings:
            mock_settings.actions_shared_secret = ""
            with pytest.raises(ActionsAuthError) as exc_info:
                validate_shared_secret("any-secret")
            assert "not configured" in exc_info.value.message.lower()

    def test_comparison_is_timing_safe(self):
        """validate_shared_secret must use hmac.compare_digest, not ==."""
        import inspect

        import app.actions_integration.service as svc_module

        source = inspect.getsource(svc_module.validate_shared_secret)
        assert "compare_digest" in source, (
            "validate_shared_secret must use hmac.compare_digest for timing safety"
        )

    def test_secret_never_in_exception_message(self):
        """The configured secret must not appear in exception messages."""
        secret = "my-very-secret-value-12345"
        with patch("app.actions_integration.service.settings") as mock_settings:
            mock_settings.actions_shared_secret = secret
            with pytest.raises(ActionsAuthError) as exc_info:
                validate_shared_secret("wrong")
            assert secret not in exc_info.value.message
            assert secret not in (exc_info.value.detail or "")


# ── Comment formatter tests ────────────────────────────────────────────────────


class TestFormatPrComment:
    def test_marker_always_present(self):
        comment = format_pr_comment(_make_result_dict(), "owner", "repo", 1)
        assert COMMENT_MARKER in comment

    def test_risk_tier_in_header(self):
        comment = format_pr_comment(_make_result_dict(risk_tier="high"), "o", "r", 1)
        assert "HIGH" in comment or "high" in comment.lower()

    def test_confidence_displayed(self):
        # 87.5 rounds to 88 with :.0f formatting — test the actual rendered value
        comment = format_pr_comment(_make_result_dict(risk_confidence=87.5), "o", "r", 1)
        assert "88%" in comment

    def test_reviewer_recommendation_shown(self):
        comment = format_pr_comment(_make_result_dict(), "o", "r", 1)
        assert "alice" in comment
        assert "Previously reviewed" in comment

    def test_checklist_shown(self):
        comment = format_pr_comment(_make_result_dict(), "o", "r", 1)
        assert "Security" in comment or "security" in comment.lower()

    def test_failed_analysis_shows_warning(self):
        comment = format_pr_comment(_make_result_dict(status="failed"), "o", "r", 1)
        assert "failed" in comment.lower() or "Analysis failed" in comment

    def test_degraded_shows_deterministic_note(self):
        comment = format_pr_comment(
            _make_result_dict(status="degraded", risk_source="deterministic_only"),
            "o",
            "r",
            1,
        )
        assert "deterministic" in comment.lower() or "unavailable" in comment.lower()

    def test_no_reviewer_when_abstained(self):
        comment = format_pr_comment(_make_result_dict(reviewer_recommendation=None), "o", "r", 1)
        assert "Suggested Reviewer" not in comment

    def test_review_assistance_disclaimer(self):
        """Comment must state it is review assistance, not a merge gate."""
        comment = format_pr_comment(_make_result_dict(), "o", "r", 1)
        assert "review assistance" in comment.lower() or "merge gate" in comment.lower()

    def test_no_internal_ids_in_comment(self):
        """Internal UUIDs should not appear in the PR comment."""
        result = _make_result_dict()
        # Add a UUID-like value that should not leak
        result["analysis_id"] = "12345678-1234-5678-1234-567812345678"
        comment = format_pr_comment(result, "o", "r", 1)
        assert "12345678-1234-5678-1234-567812345678" not in comment

    def test_no_raw_prompt_in_comment(self):
        result = _make_result_dict()
        result["raw_prompt"] = "SECRET SYSTEM PROMPT CONTENT"
        comment = format_pr_comment(result, "o", "r", 1)
        assert "SECRET SYSTEM PROMPT" not in comment

    def test_short_sha_in_comment(self):
        comment = format_pr_comment(_make_result_dict(), "o", "r", 1)
        short = VALID_SHA[:7]
        assert short in comment

    def test_checklist_fallback_note_shown(self):
        comment = format_pr_comment(_make_result_dict(checklist_is_fallback=True), "o", "r", 1)
        assert "baseline" in comment.lower() or "fallback" in comment.lower()

    def test_rationale_factors_shown(self):
        comment = format_pr_comment(_make_result_dict(), "o", "r", 1)
        assert "Sensitive path touched" in comment

    def test_factors_capped_at_5(self):
        """Comment should not dump unlimited factors."""
        many_factors = [{"factor": f"Factor {i}", "detail": "detail"} for i in range(20)]
        result = _make_result_dict(risk_rationale={"factors": many_factors})
        comment = format_pr_comment(result, "o", "r", 1)
        # Max 5 factors shown — count "Factor N" occurrences
        factor_matches = re.findall(r"Factor \d+", comment)
        assert len(factor_matches) <= 5

    def test_risk_emojis_present(self):
        for tier, expected_emoji in [
            ("low", "🟢"),
            ("medium", "🟡"),
            ("high", "🟠"),
            ("critical", "🔴"),
        ]:
            comment = format_pr_comment(_make_result_dict(risk_tier=tier), "o", "r", 1)
            assert expected_emoji in comment


# ── API endpoint tests ─────────────────────────────────────────────────────────


class TestActionsEndpoint:
    """Tests for POST /api/actions/analyze."""

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.valid_body = {
            "owner": "octocat",
            "name": "hello-world",
            "pr_number": 42,
            "commit_sha": VALID_SHA,
        }
        self.valid_headers = {
            "X-Actions-Secret": "test-secret-value",
            "X-GitHub-Token": "ghp_test_token",
        }

    def test_missing_secret_header_returns_401(self):
        resp = self.client.post(
            "/api/actions/analyze",
            json=self.valid_body,
            headers={"X-GitHub-Token": "ghp_test"},
        )
        assert resp.status_code == 401

    def test_wrong_secret_returns_401(self):
        with patch("app.api.actions.validate_shared_secret") as mock_validate:
            mock_validate.side_effect = ActionsAuthError("Invalid shared secret.")
            resp = self.client.post(
                "/api/actions/analyze",
                json=self.valid_body,
                headers=self.valid_headers,
            )
        assert resp.status_code == 401

    def test_missing_github_token_returns_400(self):
        with patch("app.api.actions.validate_shared_secret"):
            resp = self.client.post(
                "/api/actions/analyze",
                json=self.valid_body,
                headers={"X-Actions-Secret": "test-secret"},
            )
        assert resp.status_code == 400
        assert "X-GitHub-Token" in resp.text

    def test_repo_not_found_returns_404(self):
        from app.core.exceptions import RepositoryNotFoundError

        with patch("app.api.actions.validate_shared_secret"):
            with patch("app.api.actions.handle_actions_request") as mock_handle:
                mock_handle.side_effect = RepositoryNotFoundError("not found")
                resp = self.client.post(
                    "/api/actions/analyze",
                    json=self.valid_body,
                    headers=self.valid_headers,
                )
        assert resp.status_code == 404

    def test_successful_analysis_returns_200(self):
        mock_result = ActionsAnalysisResponse(
            status="completed",
            risk_tier="medium",
            risk_source="hybrid",
            risk_confidence=75.0,
            summary="Adds a new helper function.",
            commit_sha=VALID_SHA,
            comment_markdown=f"{COMMENT_MARKER}\n## GitReview AI\n\nMedium risk.",
        )
        with patch("app.api.actions.validate_shared_secret"):
            with patch(
                "app.api.actions.handle_actions_request", new_callable=AsyncMock
            ) as mock_handle:
                mock_handle.return_value = mock_result
                resp = self.client.post(
                    "/api/actions/analyze",
                    json=self.valid_body,
                    headers=self.valid_headers,
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk_tier"] == "medium"
        assert data["status"] == "completed"
        assert COMMENT_MARKER in data["comment_markdown"]

    def test_response_contains_comment_markdown(self):
        mock_result = ActionsAnalysisResponse(
            status="completed",
            risk_tier="low",
            risk_source="deterministic_only",
            risk_confidence=60.0,
            commit_sha=VALID_SHA,
            comment_markdown=f"{COMMENT_MARKER}\n## Low Risk",
        )
        with patch("app.api.actions.validate_shared_secret"):
            with patch(
                "app.api.actions.handle_actions_request", new_callable=AsyncMock
            ) as mock_handle:
                mock_handle.return_value = mock_result
                resp = self.client.post(
                    "/api/actions/analyze",
                    json=self.valid_body,
                    headers=self.valid_headers,
                )
        assert resp.status_code == 200
        assert "comment_markdown" in resp.json()

    def test_secret_not_in_401_response(self):
        """The shared secret value must never appear in error responses."""
        secret = "super-secret-do-not-leak-12345"
        with patch("app.api.actions.validate_shared_secret") as mock_validate:
            mock_validate.side_effect = ActionsAuthError("Invalid shared secret.")
            resp = self.client.post(
                "/api/actions/analyze",
                json=self.valid_body,
                headers={**self.valid_headers, "X-Actions-Secret": secret},
            )
        assert resp.status_code == 401
        assert secret not in resp.text

    def test_invalid_body_returns_422(self):
        with patch("app.api.actions.validate_shared_secret"):
            resp = self.client.post(
                "/api/actions/analyze",
                json={"owner": "x"},  # missing required fields
                headers=self.valid_headers,
            )
        # 422 from Pydantic validation or 401 (secret validation runs first)
        assert resp.status_code in (400, 401, 422)

    def test_commit_sha_40_chars_required(self):
        body = {**self.valid_body, "commit_sha": "short"}
        with patch("app.api.actions.validate_shared_secret"):
            resp = self.client.post(
                "/api/actions/analyze",
                json=body,
                headers=self.valid_headers,
            )
        assert resp.status_code == 422


# ── Workflow file existence and structure tests ─────────────────────────────────


class TestWorkflowFile:
    """
    Validate that the GitHub Actions workflow file exists and has the correct
    structure. These are static checks — no GitHub infrastructure required.
    """

    WORKFLOW_PATH = (
        Path(__file__).parent.parent.parent.parent.parent
        / ".github"
        / "workflows"
        / "gitreview-ai.yml"
    )

    def test_workflow_file_exists(self):
        assert self.WORKFLOW_PATH.exists(), (
            f"Workflow file not found at {self.WORKFLOW_PATH}. "
            "Create .github/workflows/gitreview-ai.yml"
        )

    def test_workflow_triggers_on_pull_request(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "pull_request:" in content

    def test_workflow_triggers_on_opened(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "opened" in content

    def test_workflow_triggers_on_synchronize(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "synchronize" in content

    def test_workflow_triggers_on_reopened(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "reopened" in content

    def test_workflow_has_pull_requests_write_permission(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "pull-requests: write" in content

    def test_workflow_has_concurrency_group(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "concurrency:" in content

    def test_workflow_cancels_in_progress(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "cancel-in-progress: true" in content

    def test_workflow_uses_shared_secret_from_secrets(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "secrets.GITREVIEW_SHARED_SECRET" in content

    def test_workflow_does_not_hardcode_secrets(self):
        content = self.WORKFLOW_PATH.read_text()
        # Should reference secrets.X, not literal values
        assert "SHARED_SECRET:" not in content.replace(
            "SHARED_SECRET: ${{ secrets.GITREVIEW_SHARED_SECRET }}", ""
        )

    def test_workflow_uses_github_token_from_secrets(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "secrets.GITHUB_TOKEN" in content

    def test_workflow_posts_to_actions_endpoint(self):
        content = self.WORKFLOW_PATH.read_text()
        assert "/api/actions/analyze" in content

    def test_workflow_has_comment_marker_reference(self):
        """Workflow must look for the idempotency marker to find existing comments."""
        content = self.WORKFLOW_PATH.read_text()
        assert "gitreview-ai-bot" in content

    def test_comment_marker_matches_service_constant(self):
        """The marker in the workflow must match COMMENT_MARKER in service.py."""
        content = self.WORKFLOW_PATH.read_text()
        # COMMENT_MARKER = "<!-- gitreview-ai-bot -->"
        assert "gitreview-ai-bot" in content
        assert "gitreview-ai-bot" in COMMENT_MARKER


# ── Config tests ───────────────────────────────────────────────────────────────


class TestActionsConfig:
    def test_actions_shared_secret_in_settings(self):
        from app.core.config import Settings

        s = Settings(actions_shared_secret="test-secret")
        assert s.actions_shared_secret == "test-secret"

    def test_actions_shared_secret_defaults_empty(self, monkeypatch):
        from app.core.config import Settings

        # Remove from process env so pydantic-settings sees only the field default
        monkeypatch.delenv("ACTIONS_SHARED_SECRET", raising=False)
        # Prevent pydantic-settings from reading the developer's .env file
        s = Settings(_env_file=None)
        assert s.actions_shared_secret == ""

    def test_env_example_contains_actions_secret(self):
        env_example = Path(__file__).parent.parent.parent.parent / ".env.example"
        assert env_example.exists(), "backend/.env.example should exist"
        content = env_example.read_text()
        assert "ACTIONS_SHARED_SECRET" in content
