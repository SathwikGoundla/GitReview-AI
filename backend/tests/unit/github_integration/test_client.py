"""Unit tests for app.github_integration.client — CODEOWNERS parsing and helpers."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")


class TestCodeownersParsing:
    def setup_method(self):
        from app.github_integration.client import GitHubApiClient

        self.client = GitHubApiClient.__new__(GitHubApiClient)

    def test_basic_codeowners(self):
        content = "src/auth/ @alice @bob\n*.py @carol\n"
        result = self.client._parse_codeowners(content)
        assert "src/auth/" in result
        assert "alice" in result["src/auth/"]
        assert "bob" in result["src/auth/"]
        assert "*.py" in result
        assert "carol" in result["*.py"]

    def test_comments_ignored(self):
        content = "# This is a comment\nsrc/ @alice\n"
        result = self.client._parse_codeowners(content)
        assert "src/" in result
        assert len(result) == 1

    def test_empty_lines_ignored(self):
        content = "\n\nsrc/ @alice\n\n\n*.py @bob\n"
        result = self.client._parse_codeowners(content)
        assert len(result) == 2

    def test_at_sign_stripped_from_owners(self):
        content = "src/ @alice @bob\n"
        result = self.client._parse_codeowners(content)
        for owner in result["src/"]:
            assert not owner.startswith("@")

    def test_line_without_owners_ignored(self):
        content = "src/\n*.py @bob\n"
        result = self.client._parse_codeowners(content)
        # "src/" has no @owners, so it should be skipped
        assert "src/" not in result
        assert "*.py" in result

    def test_empty_codeowners(self):
        result = self.client._parse_codeowners("")
        assert result == {}


class TestRaiseForStatus:
    def setup_method(self):
        import httpx

        from app.github_integration.client import GitHubApiClient

        self.client = GitHubApiClient.__new__(GitHubApiClient)
        self.httpx = httpx

    def _make_response(self, status_code: int, text: str = "") -> object:
        """Create a minimal mock httpx.Response-like object."""

        class FakeResponse:
            def __init__(self, code, body):
                self.status_code = code
                self.text = body
                self.url = "https://api.github.com/test"

            @property
            def is_success(self):
                return 200 <= self.status_code < 300

        return FakeResponse(status_code, text)

    def test_404_raises_not_found(self):
        from app.core.exceptions import GitHubNotFoundError

        resp = self._make_response(404)
        with pytest.raises(GitHubNotFoundError):
            self.client._raise_for_status(resp)

    def test_403_raises_permission(self):
        from app.core.exceptions import GitHubPermissionError

        resp = self._make_response(403)
        with pytest.raises(GitHubPermissionError):
            self.client._raise_for_status(resp)

    def test_429_raises_rate_limit(self):
        from app.core.exceptions import GitHubRateLimitError

        resp = self._make_response(429)
        with pytest.raises(GitHubRateLimitError):
            self.client._raise_for_status(resp)

    def test_500_raises_github_error(self):
        from app.core.exceptions import GitHubError

        resp = self._make_response(500, "Internal Server Error")
        with pytest.raises(GitHubError):
            self.client._raise_for_status(resp)

    def test_200_does_not_raise(self):
        resp = self._make_response(200)
        self.client._raise_for_status(resp)  # Should not raise


class TestPRDataFields:
    def test_pr_data_construction(self):
        from app.github_integration.client import PRData

        pr = PRData(
            repo_owner="acme",
            repo_name="backend",
            github_repo_id=12345,
            pr_number=7,
            pr_title="Fix login bug",
            author_username="alice",
            base_branch="main",
            head_branch="fix/login",
            commit_sha="a" * 40,
            state="open",
            changed_files=["auth/login.py"],
            diff_text="",
            lines_added=10,
            lines_removed=5,
            commit_messages=["Fix login bug"],
        )
        assert pr.repo_owner == "acme"
        assert pr.commit_sha == "a" * 40
        assert pr.lines_added == 10
        assert pr.state == "open"

    def test_pr_data_defaults(self):
        from app.github_integration.client import PRData

        pr = PRData(
            repo_owner="a",
            repo_name="b",
            github_repo_id=1,
            pr_number=1,
            pr_title="T",
            author_username="u",
            base_branch="main",
            head_branch="feat",
            commit_sha="c" * 40,
            state="open",
        )
        assert pr.changed_files == []
        assert pr.diff_text == ""
        assert pr.commit_messages == []
        assert pr.codeowners_entries == []
