"""
GitReview AI — Authentication Schemas (Pydantic)

Request and response shapes for the /api/auth/* endpoints.
Schemas are kept minimal: they reflect what the API actually sends and receives,
not hypothetical future fields.

All sensitive values (tokens, secrets) are write-only going into the API
and are never included in response schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── Responses ─────────────────────────────────────────────────────────────────


class LoginInitResponse(BaseModel):
    """
    Returned by GET /api/auth/login.
    The extension opens authorize_url in a popup/tab to start the OAuth flow.
    The state value must be stored by the client and sent back on the callback
    so the server can verify it matches the signed CSRF token.
    """

    authorize_url: str = Field(description="GitHub OAuth authorization URL.")
    state: str = Field(description="Signed CSRF state token. Store and send on callback.")


class UserProfile(BaseModel):
    """Public user identity fields safe to include in responses."""

    id: uuid.UUID
    github_username: str
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class CallbackResponse(BaseModel):
    """
    Returned by GET /api/auth/callback after a successful OAuth exchange.
    The session_token is the raw opaque token the extension stores in
    chrome.storage.local and sends on every subsequent request.
    It is only ever returned once — future requests use it, they never receive it again.
    """

    session_token: str = Field(
        description="Opaque session token. Store securely; sent on every request."
    )
    user: UserProfile


class LogoutResponse(BaseModel):
    """Returned by POST /api/auth/logout."""

    message: str = "Logged out successfully."


class CurrentUserResponse(BaseModel):
    """
    Returned by GET /api/auth/me — the authenticated user's profile.
    Used by the extension to confirm who is signed in on load.
    """

    id: uuid.UUID
    github_username: str
    avatar_url: str | None = None
    session_issued_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Error response (shared shape) ─────────────────────────────────────────────


class ErrorResponse(BaseModel):
    """Standard error envelope returned on all 4xx/5xx responses."""

    error: str = Field(description="Machine-readable error code.")
    message: str = Field(description="Human-readable description.")
    detail: str | None = Field(default=None, description="Additional context, if available.")
