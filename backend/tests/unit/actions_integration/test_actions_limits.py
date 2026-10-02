import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.github_integration.client import PRData
from backend.tests.e2e.test_actions_flow_e2e import setup_authorized_repo, _ActionsSessionLocal, TEST_ACTIONS_SECRET, VALID_40_CHAR_SHA

client = TestClient(app)

@pytest.mark.asyncio
async def test_actions_analyze_oversized_pr(monkeypatch):
    from app.core.config import Settings
    settings = Settings(max_pr_lines=3000, max_pr_bytes=1024, actions_shared_secret=TEST_ACTIONS_SECRET)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)

    # Setup the authorized repo
    async with _ActionsSessionLocal() as session:
        await setup_authorized_repo(session, "actions-owner", "actions-repo")

    # Mock PR data to exceed size limits (e.g., 5000 lines)
    oversized_pr_data = PRData(
        repo_owner="actions-owner",
        repo_name="actions-repo",
        github_repo_id=777,
        pr_number=99,
        pr_title="Huge PR",
        author_username="user1",
        base_branch="main",
        head_branch="huge-feature",
        commit_sha=VALID_40_CHAR_SHA,
        state="open",
        changed_files=["huge.py"],
        diff_text="a" * 1024,
        lines_added=4000,
        lines_removed=2000,
        commit_messages=["Huge commit"]
    )
    
    with patch("app.github_integration.client.GitHubApiClient.fetch_pull_request_data", AsyncMock(return_value=oversized_pr_data)):
        payload = {
            "owner": "actions-owner",
            "name": "actions-repo",
            "pr_number": 99,
            "commit_sha": VALID_40_CHAR_SHA,
        }
        headers = {
            "X-Actions-Secret": TEST_ACTIONS_SECRET,
            "X-GitHub-Token": "ghp_actions_token",
        }
        
        response = client.post("/api/actions/analyze", json=payload, headers=headers)
        
        assert response.status_code == 413
        data = response.json()
        assert data["detail"]["error_code"] == "PR_TOO_LARGE"
