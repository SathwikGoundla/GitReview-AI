import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.analysis.orchestrator import AnalysisOrchestrator
from app.core.exceptions import PRTooLargeError
from app.core.models import PullRequest, Repository
from app.github_integration.client import PRData


@pytest.fixture
def mock_orchestrator():
    return AnalysisOrchestrator(
        ai_provider=AsyncMock(),
        prompt_builder=MagicMock(),
        validator=MagicMock(),
        risk_engine=MagicMock(),
        confidence_calculator=MagicMock(),
        reviewer_service=MagicMock(),
        checklist_generator=MagicMock(),
    )


@pytest.fixture
def mock_pull_request():
    repo = Repository(id=uuid.uuid4(), owner="test_owner", name="test_repo")
    return PullRequest(id=uuid.uuid4(), repository_id=repo.id, repository=repo, github_pr_number=1)


@pytest.mark.asyncio
async def test_pr_size_limit_exact_boundary(mock_orchestrator, mock_pull_request, monkeypatch):
    from app.core.config import Settings

    settings = Settings(max_pr_lines=3000, max_pr_bytes=1024)
    monkeypatch.setattr("app.analysis.orchestrator.get_settings", lambda: settings)

    github_client = AsyncMock()
    # Exact byte and line limit
    pr_data = PRData(
        repo_owner="test_owner",
        repo_name="test_repo",
        github_repo_id=1,
        pr_number=1,
        pr_title="title",
        author_username="author",
        base_branch="main",
        head_branch="feature",
        commit_sha="sha",
        state="open",
        lines_added=1500,
        lines_removed=1500,
        diff_text="a" * 1024,
    )
    github_client.fetch_pull_request_data.return_value = pr_data
    github_client.fetch_contribution_history.return_value = ([], [])
    github_client.fetch_codeowners.return_value = {}
    github_client.fetch_collaborators.return_value = []

    # We mock _check_cache to return None so it proceeds
    mock_orchestrator._check_cache = AsyncMock(return_value=None)
    mock_orchestrator._call_ai_with_retry = AsyncMock(return_value=({"checklist": []}, False, True))
    mock_orchestrator._persist_result = AsyncMock(return_value=MagicMock())

    # Should not raise
    await mock_orchestrator.run_analysis(
        db=AsyncMock(),
        pull_request=mock_pull_request,
        commit_sha="sha",
        github_client=github_client,
    )


@pytest.mark.asyncio
async def test_pr_size_limit_lines_exceeded(mock_orchestrator, mock_pull_request, monkeypatch):
    from app.core.config import Settings

    settings = Settings(max_pr_lines=3000, max_pr_bytes=1024)
    monkeypatch.setattr("app.analysis.orchestrator.get_settings", lambda: settings)

    github_client = AsyncMock()
    # 3001 lines
    pr_data = PRData(
        repo_owner="test_owner",
        repo_name="test_repo",
        github_repo_id=1,
        pr_number=1,
        pr_title="title",
        author_username="author",
        base_branch="main",
        head_branch="feature",
        commit_sha="sha",
        state="open",
        lines_added=1500,
        lines_removed=1501,
        diff_text="a" * 1024,
    )
    github_client.fetch_pull_request_data.return_value = pr_data

    mock_orchestrator._check_cache = AsyncMock(return_value=None)
    mock_orchestrator._call_ai_with_retry = AsyncMock()
    mock_orchestrator._persist_result = AsyncMock()

    with pytest.raises(PRTooLargeError) as exc_info:
        await mock_orchestrator.run_analysis(
            db=AsyncMock(),
            pull_request=mock_pull_request,
            commit_sha="sha",
            github_client=github_client,
        )

    assert exc_info.value.http_status == 413
    assert exc_info.value.error_code == "PR_TOO_LARGE"

    # Assert no AI call and no persistence
    mock_orchestrator._call_ai_with_retry.assert_not_called()
    mock_orchestrator._persist_result.assert_not_called()


@pytest.mark.asyncio
async def test_pr_size_limit_bytes_exceeded(mock_orchestrator, mock_pull_request, monkeypatch):
    from app.core.config import Settings

    settings = Settings(max_pr_lines=3000, max_pr_bytes=1024)
    monkeypatch.setattr("app.analysis.orchestrator.get_settings", lambda: settings)

    github_client = AsyncMock()
    # 1025 bytes
    pr_data = PRData(
        repo_owner="test_owner",
        repo_name="test_repo",
        github_repo_id=1,
        pr_number=1,
        pr_title="title",
        author_username="author",
        base_branch="main",
        head_branch="feature",
        commit_sha="sha",
        state="open",
        lines_added=1500,
        lines_removed=1500,
        diff_text="a" * 1025,
    )
    github_client.fetch_pull_request_data.return_value = pr_data

    mock_orchestrator._check_cache = AsyncMock(return_value=None)
    mock_orchestrator._call_ai_with_retry = AsyncMock()
    mock_orchestrator._persist_result = AsyncMock()

    with pytest.raises(PRTooLargeError) as exc_info:
        await mock_orchestrator.run_analysis(
            db=AsyncMock(),
            pull_request=mock_pull_request,
            commit_sha="sha",
            github_client=github_client,
        )

    assert exc_info.value.http_status == 413
    assert exc_info.value.error_code == "PR_TOO_LARGE"

    # Assert no AI call and no persistence
    mock_orchestrator._call_ai_with_retry.assert_not_called()
    mock_orchestrator._persist_result.assert_not_called()


# ── Recorded model name must reflect the configured model ──────────────────────


@pytest.mark.asyncio
async def test_persisted_model_name_uses_configured_gemini_model(
    mock_orchestrator, mock_pull_request, monkeypatch
):
    from app.core.config import Settings
    from app.core.models import PullRequestAnalysis

    settings = Settings(gemini_model="gemini-custom-test-model")
    monkeypatch.setattr("app.analysis.orchestrator.get_settings", lambda: settings)

    added = []
    db = MagicMock()
    db.add = added.append

    async def _flush():
        for obj in added:
            if isinstance(obj, PullRequestAnalysis) and obj.id is None:
                obj.id = uuid.uuid4()

    db.flush = _flush
    # Stop after the main record is created: later steps need rich mocks we don't care about here.
    with pytest.raises(Exception):
        await mock_orchestrator._persist_result(
            db, mock_pull_request, "a" * 40, MagicMock(), None, MagicMock(), 50.0,
            MagicMock(), MagicMock(), "extension", "completed",
        )  # fmt: skip

    analyses = [o for o in added if isinstance(o, PullRequestAnalysis)]
    assert len(analyses) == 1
    assert analyses[0].model_name == "gemini-custom-test-model"


def test_analysis_result_default_model_name_follows_settings(monkeypatch):
    from app.analysis.orchestrator import AnalysisResult
    from app.core.config import Settings

    settings = Settings(gemini_model="gemini-another-model")
    monkeypatch.setattr("app.analysis.orchestrator.get_settings", lambda: settings)
    fields = AnalysisResult.__dataclass_fields__["model_name"]
    assert fields.default_factory() == "gemini-another-model"
