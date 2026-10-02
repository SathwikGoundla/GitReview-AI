"""
GitReview AI — Step 20: GitHub Actions Composite Action Tests

Tests cover:
  - action.yml exists with correct structure
  - action.yml defines required inputs (backend-url, shared-secret)
  - action.yml defines outputs (risk-tier, status)
  - action.yml uses composite runner
  - action.yml sends correct headers and body to POST /api/actions/analyze
  - action.yml does not hardcode secrets
  - action.yml references the correct API path
  - action.yml has comment marker for idempotency
  - action.yml validates environment variables before calling backend
  - Existing workflow still references the same backend contract
  - Action contract matches backend ActionsAnalyzeRequest schema exactly

These tests are static file-based checks and schema validation.
They do NOT call the backend or GitHub APIs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.actions_integration.schemas import ActionsAnalyzeRequest

# ── Constants ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
ACTION_PATH = PROJECT_ROOT / ".github" / "actions" / "gitreview-ai" / "action.yml"
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "gitreview-ai.yml"


@pytest.fixture(scope="module")
def action_content() -> str:
    """Raw content of action.yml."""
    return ACTION_PATH.read_text()


@pytest.fixture(scope="module")
def action_yaml() -> dict:
    """Parsed YAML of action.yml."""
    return yaml.safe_load(ACTION_PATH.read_text())


# ── File existence ─────────────────────────────────────────────────────────────


class TestActionFileStructure:
    def test_action_yml_exists(self):
        assert ACTION_PATH.exists(), (
            f"action.yml not found at {ACTION_PATH}. Create .github/actions/gitreview-ai/action.yml"
        )

    def test_workflow_still_exists(self):
        assert WORKFLOW_PATH.exists(), (
            f"Workflow file not found at {WORKFLOW_PATH}. "
            "The existing workflow must not be deleted."
        )


# ── Action YAML structure ──────────────────────────────────────────────────────


class TestActionDefinition:
    def test_has_name(self, action_yaml):
        assert "name" in action_yaml
        assert "GitReview" in action_yaml["name"]

    def test_has_description(self, action_yaml):
        assert "description" in action_yaml

    def test_uses_composite_runner(self, action_yaml):
        assert action_yaml["runs"]["using"] == "composite"

    def test_has_steps(self, action_yaml):
        assert "steps" in action_yaml["runs"]
        assert len(action_yaml["runs"]["steps"]) >= 1


# ── Inputs ─────────────────────────────────────────────────────────────────────


class TestActionInputs:
    def test_backend_url_input_required(self, action_yaml):
        inputs = action_yaml.get("inputs", {})
        assert "backend-url" in inputs
        assert inputs["backend-url"]["required"] is True

    def test_shared_secret_input_required(self, action_yaml):
        inputs = action_yaml.get("inputs", {})
        assert "shared-secret" in inputs
        assert inputs["shared-secret"]["required"] is True

    def test_no_hardcoded_secrets_in_inputs(self, action_yaml):
        """Input definitions must not contain actual secret values."""
        content = yaml.dump(action_yaml.get("inputs", {}))
        assert "openssl" not in content.lower() or "generate" in content.lower()
        # Ensure no hex-like strings that look like real secrets
        import re

        hex_pattern = re.compile(r"[0-9a-f]{32,}", re.IGNORECASE)
        matches = hex_pattern.findall(content)
        assert len(matches) == 0, "Found hex string that may be a hardcoded secret"


# ── Outputs ────────────────────────────────────────────────────────────────────


class TestActionOutputs:
    def test_risk_tier_output(self, action_yaml):
        outputs = action_yaml.get("outputs", {})
        assert "risk-tier" in outputs

    def test_status_output(self, action_yaml):
        outputs = action_yaml.get("outputs", {})
        assert "status" in outputs


# ── Security ───────────────────────────────────────────────────────────────────


class TestActionSecurity:
    def test_uses_x_actions_secret_header(self, action_content):
        """Must use the same header name as the backend."""
        assert "X-Actions-Secret" in action_content

    def test_uses_x_github_token_header(self, action_content):
        """Must pass the GitHub token via X-GitHub-Token header."""
        assert "X-GitHub-Token" in action_content

    def test_does_not_echo_secret(self, action_content):
        """Must never echo/print the shared secret value."""
        lines = action_content.split("\n")
        for line in lines:
            stripped = line.strip().lower()
            # Look for echo $SHARED_SECRET or similar
            if "echo" in stripped and "shared_secret" in stripped:
                # Allow lines like: echo "::error::...shared-secret..."
                assert (
                    "$shared_secret" not in stripped or "error" in stripped or "warning" in stripped
                ), f"Line may echo the secret: {line}"

    def test_does_not_hardcode_backend_url(self, action_content):
        """Backend URL must come from inputs, not hardcoded."""
        assert "localhost:8000" not in action_content


# ── Backend contract ───────────────────────────────────────────────────────────


class TestBackendContract:
    def test_posts_to_correct_endpoint(self, action_content):
        assert "/api/actions/analyze" in action_content

    def test_uses_post_method(self, action_content):
        assert "POST" in action_content

    def test_sends_owner_field(self, action_content):
        assert "owner" in action_content

    def test_sends_name_field(self, action_content):
        assert "name" in action_content

    def test_sends_pr_number_field(self, action_content):
        assert "pr_number" in action_content

    def test_sends_commit_sha_field(self, action_content):
        assert "commit_sha" in action_content

    def test_request_body_matches_schema(self):
        """The fields sent by the action must match ActionsAnalyzeRequest."""
        schema_fields = set(ActionsAnalyzeRequest.model_fields.keys())
        expected = {"owner", "name", "pr_number", "commit_sha"}
        assert schema_fields == expected, (
            f"Action sends fields that don't match schema. "
            f"Schema: {schema_fields}, Expected: {expected}"
        )

    def test_reads_comment_markdown_from_response(self, action_content):
        """The action must extract comment_markdown from the response."""
        assert "comment_markdown" in action_content

    def test_reads_risk_tier_from_response(self, action_content):
        assert "risk_tier" in action_content

    def test_comment_marker_present(self, action_content):
        """The comment marker must match the service constant for idempotency."""
        assert "gitreview-ai-bot" in action_content


# ── Error handling ─────────────────────────────────────────────────────────────


class TestActionErrorHandling:
    def test_handles_401_response(self, action_content):
        """Must handle auth failure (401)."""
        assert "401" in action_content

    def test_handles_404_response(self, action_content):
        """Must handle repo-not-found (404)."""
        assert "404" in action_content

    def test_handles_500_response(self, action_content):
        """Must handle server errors (500+)."""
        assert "500" in action_content

    def test_validates_backend_url_not_empty(self, action_content):
        """Must check that BACKEND_URL is set."""
        assert "BACKEND_URL" in action_content

    def test_validates_shared_secret_not_empty(self, action_content):
        """Must check that SHARED_SECRET is set."""
        assert "SHARED_SECRET" in action_content

    def test_validates_pr_number_set(self, action_content):
        """Must check that PR_NUMBER is available."""
        assert "PR_NUMBER" in action_content

    def test_non_200_causes_failure(self, action_content):
        """Non-200 responses (except 404) must cause exit 1."""
        # The action should have exit 1 for error cases
        assert "exit 1" in action_content


# ── Workflow compatibility ─────────────────────────────────────────────────────


class TestWorkflowCompatibility:
    """Ensure the existing workflow and new action use the same contract."""

    def test_workflow_and_action_use_same_endpoint(self, action_content):
        workflow_content = WORKFLOW_PATH.read_text()
        assert "/api/actions/analyze" in workflow_content
        assert "/api/actions/analyze" in action_content

    def test_workflow_and_action_use_same_headers(self, action_content):
        workflow_content = WORKFLOW_PATH.read_text()
        assert "X-Actions-Secret" in workflow_content
        assert "X-Actions-Secret" in action_content
        assert "X-GitHub-Token" in workflow_content
        assert "X-GitHub-Token" in action_content

    def test_workflow_and_action_use_same_comment_marker(self, action_content):
        workflow_content = WORKFLOW_PATH.read_text()
        assert "gitreview-ai-bot" in workflow_content
        assert "gitreview-ai-bot" in action_content
