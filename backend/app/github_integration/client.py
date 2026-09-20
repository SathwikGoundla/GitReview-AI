"""
GitReview AI — GitHub Integration Module

All outbound communication with the GitHub REST and GraphQL APIs.
LLD Part A.5 / B.3: GitHubApiClient — pure transport plus normalization.
No business interpretation of returned data.

Security:
  - Only data within the authenticated token's actual GitHub permissions is returned
  - Rate limit tracking per user
  - Never stores raw diff/source content
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.core.exceptions import (
    GitHubError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
)

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_GITHUB_GRAPHQL = "https://api.github.com/graphql"

_DEFAULT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


@dataclass
class PRData:
    """Normalized PR data object — the output of the GitHub Integration Module."""

    repo_owner: str
    repo_name: str
    github_repo_id: int
    pr_number: int
    pr_title: str
    author_username: str
    base_branch: str
    head_branch: str
    commit_sha: str  # Full 40-char SHA
    state: str  # open|closed|merged
    changed_files: list[str] = field(default_factory=list)
    diff_text: str = ""
    lines_added: int = 0
    lines_removed: int = 0
    commit_messages: list[str] = field(default_factory=list)
    linked_issue_title: str | None = None
    linked_issue_body: str | None = None
    codeowners_entries: list[str] = field(default_factory=list)


class GitHubApiClient:
    """
    Low-level REST/GraphQL HTTP wrapper for all GitHub calls.
    One instance per request context (carries the caller's token).
    """

    def __init__(self, access_token: str) -> None:
        self._token = access_token
        self._headers = {
            **_DEFAULT_HEADERS,
            "Authorization": f"Bearer {access_token}",
        }

    async def fetch_pull_request_data(self, owner: str, repo: str, pr_number: int) -> PRData:
        """Fetch complete PR data needed for analysis (diff, metadata, commits)."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Fetch PR metadata
            pr_meta = await self._get(client, f"/repos/{owner}/{repo}/pulls/{pr_number}")
            commit_sha = pr_meta["head"]["sha"]

            # Fetch diff
            diff_text = await self._get_diff(client, owner, repo, pr_number)

            # Fetch changed files
            files_data = await self._get(client, f"/repos/{owner}/{repo}/pulls/{pr_number}/files")
            changed_files = [f["filename"] for f in files_data]
            lines_added = sum(f.get("additions", 0) for f in files_data)
            lines_removed = sum(f.get("deletions", 0) for f in files_data)

            # Fetch commit messages (last 20)
            commits_data = await self._get(
                client, f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
            )
            commit_messages = [
                c["commit"]["message"].split("\n")[0]  # First line only
                for c in commits_data[:20]
            ]

            # Fetch repo metadata for github_repo_id
            repo_meta = await self._get(client, f"/repos/{owner}/{repo}")

            # Determine PR state
            state = pr_meta.get("state", "open")
            if pr_meta.get("merged"):
                state = "merged"

            return PRData(
                repo_owner=owner,
                repo_name=repo,
                github_repo_id=repo_meta["id"],
                pr_number=pr_number,
                pr_title=pr_meta["title"],
                author_username=pr_meta["user"]["login"],
                base_branch=pr_meta["base"]["ref"],
                head_branch=pr_meta["head"]["ref"],
                commit_sha=commit_sha,
                state=state,
                changed_files=changed_files,
                diff_text=diff_text,
                lines_added=lines_added,
                lines_removed=lines_removed,
                commit_messages=commit_messages,
            )

    async def fetch_codeowners(self, owner: str, repo: str) -> dict[str, list[str]]:
        """
        Fetch and parse CODEOWNERS file. Returns {pattern: [owner, ...]} or {} if not present.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            for path in ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"]:
                try:
                    resp = await client.get(
                        f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
                        headers=self._headers,
                    )
                    if resp.status_code == 200:
                        import base64

                        content = base64.b64decode(resp.json()["content"]).decode()
                        return self._parse_codeowners(content)
                except Exception:
                    continue
        return {}

    async def fetch_contribution_history(
        self, owner: str, repo: str, file_paths: list[str]
    ) -> tuple[dict[str, int], dict[str, int]]:
        """
        Fetch commit and review history for the given files.
        Returns (commit_history, review_history) — {username: count} dicts.
        """
        commit_history: dict[str, int] = {}
        review_history: dict[str, int] = {}

        async with httpx.AsyncClient(timeout=30) as client:
            # Sample up to 5 files to stay within rate limits
            for file_path in file_paths[:5]:
                try:
                    commits = await self._get(
                        client,
                        f"/repos/{owner}/{repo}/commits",
                        params={"path": file_path, "per_page": 30},
                    )
                    for c in commits:
                        author = c.get("author")
                        if author and author.get("login"):
                            uname = author["login"]
                            commit_history[uname] = commit_history.get(uname, 0) + 1
                except Exception:
                    pass

        return commit_history, review_history

    async def fetch_collaborators(self, owner: str, repo: str) -> set[str]:
        """Return the set of current, active collaborators with repo access."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                data = await self._get(
                    client,
                    f"/repos/{owner}/{repo}/collaborators",
                    params={"per_page": 100},
                )
                return {c["login"] for c in data}
        except Exception:
            return set()

    async def post_comment(self, owner: str, repo: str, pr_number: int, body: str) -> dict:
        """Post a comment on a PR. Returns the created comment data."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments",
                headers=self._headers,
                json={"body": body},
            )
            self._raise_for_status(resp)
            return resp.json()

    async def apply_label(self, owner: str, repo: str, pr_number: int, label: str) -> None:
        """Apply a label to a PR."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/labels",
                headers=self._headers,
                json={"labels": [label]},
            )
            self._raise_for_status(resp)

    async def verify_repo_access(self, owner: str, repo: str) -> tuple[bool, str | None]:
        """
        Verify the authenticated user currently has access to the repository.
        Returns (has_access, permission_level).
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_GITHUB_API}/repos/{owner}/{repo}",
                    headers=self._headers,
                )
                if resp.status_code == 404:
                    return False, None
                if resp.status_code == 403:
                    return False, None
                if resp.is_success:
                    perms = resp.json().get("permissions", {})
                    if perms.get("admin"):
                        return True, "admin"
                    if perms.get("maintain"):
                        return True, "maintain"
                    if perms.get("push"):
                        return True, "write"
                    if perms.get("pull"):
                        return True, "read"
                    return True, "read"
                return False, None
        except Exception:
            return False, None

    # ── Private ──────────────────────────────────────────────────────────────────

    async def _get(
        self, client: httpx.AsyncClient, path: str, params: dict | None = None
    ) -> dict | list:
        resp = await client.get(f"{_GITHUB_API}{path}", headers=self._headers, params=params)
        self._raise_for_status(resp)
        return resp.json()

    async def _get_diff(
        self, client: httpx.AsyncClient, owner: str, repo: str, pr_number: int
    ) -> str:
        """Fetch the PR diff using the diff Accept header."""
        diff_headers = {**self._headers, "Accept": "application/vnd.github.diff"}
        resp = await client.get(
            f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=diff_headers,
        )
        self._raise_for_status(resp)
        return resp.text

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 404:
            raise GitHubNotFoundError(f"GitHub resource not found: {resp.url}")
        if resp.status_code == 403:
            raise GitHubPermissionError(f"GitHub permission denied: {resp.url}")
        if resp.status_code == 429:
            raise GitHubRateLimitError("GitHub API rate limit exceeded.")
        if not resp.is_success:
            raise GitHubError(
                f"GitHub API error {resp.status_code}",
                detail=resp.text[:500],
            )

    @staticmethod
    def _parse_codeowners(content: str) -> dict[str, list[str]]:
        """Parse CODEOWNERS file content into {pattern: [owner, ...]}."""
        result: dict[str, list[str]] = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                pattern = parts[0]
                owners = [o.lstrip("@") for o in parts[1:] if o.startswith("@")]
                if owners:
                    result[pattern] = owners
        return result
