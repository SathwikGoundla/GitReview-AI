"""
GitReview AI — Repository Schemas (Pydantic)

Request and response shapes for /api/repositories/* endpoints.

Security note:
  - No GitHub OAuth tokens, session hashes, or encrypted credentials are exposed.
  - Only fields appropriate for the authenticated user are returned.
  - internal database UUIDs are exposed for repository_id (safe — not sequential,
    and access is enforced at the service layer).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── Request schemas ───────────────────────────────────────────────────────────


class AuthorizeRepositoryRequest(BaseModel):
    """
    Body for POST /api/repositories/authorize.
    The client supplies owner and name; the server verifies GitHub access
    and fetches the canonical github_repo_id — we never trust the client
    to supply a repository_id directly for authorization.
    """

    owner: str = Field(
        description="GitHub repository owner login (user or org).",
        min_length=1,
        max_length=100,
    )
    name: str = Field(
        description="GitHub repository name (without the owner prefix).",
        min_length=1,
        max_length=100,
    )


# ── Response schemas ──────────────────────────────────────────────────────────


class RepositoryResponse(BaseModel):
    """
    Public representation of a repository.
    Safe to return to the authenticated user.
    """

    id: uuid.UUID = Field(description="Internal GitReview AI repository ID.")
    github_repo_id: int = Field(description="GitHub's own numeric repository ID.")
    owner: str = Field(description="GitHub owner login.")
    name: str = Field(description="Repository name.")
    full_name: str = Field(description="owner/name formatted string.")
    default_branch: str | None = Field(default=None, description="Default branch name.")

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_full_name(cls, repo) -> RepositoryResponse:
        return cls(
            id=repo.id,
            github_repo_id=repo.github_repo_id,
            owner=repo.owner,
            name=repo.name,
            full_name=f"{repo.owner}/{repo.name}",
            default_branch=repo.default_branch,
        )


class RepositoryAccessResponse(BaseModel):
    """
    The calling user's access record for one repository.
    Returned alongside the repository in list/authorize responses.
    """

    repository_id: uuid.UUID
    github_permission_level: str | None = None
    authorized_at: datetime
    is_active: bool = Field(description="True when revoked_at is NULL.")

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, access) -> RepositoryAccessResponse:
        return cls(
            repository_id=access.repository_id,
            github_permission_level=access.github_permission_level,
            authorized_at=access.authorized_at,
            is_active=access.revoked_at is None,
        )


class AuthorizedRepositoryItem(BaseModel):
    """One item in the authorized-repository list."""

    repository: RepositoryResponse
    access: RepositoryAccessResponse


class RepositoryListResponse(BaseModel):
    """Response for GET /api/repositories."""

    repositories: list[AuthorizedRepositoryItem]
    total: int


class AuthorizeRepositoryResponse(BaseModel):
    """Response for POST /api/repositories/authorize."""

    repository: RepositoryResponse
    access: RepositoryAccessResponse
    message: str = "Repository authorized successfully."


class RevokeAccessResponse(BaseModel):
    """Response for DELETE /api/repositories/{repository_id}/access."""

    message: str = "Repository access revoked."
    repository_id: uuid.UUID
