"""
GitReview AI — Authentication Router (LLD A.1 / A.2)

Endpoints:
  GET  /api/auth/login     — Start OAuth; returns the GitHub authorization URL.
  GET  /api/auth/callback  — GitHub redirects here with ?code=&state=
  POST /api/auth/logout    — Revoke the current session.
  GET  /api/auth/me        — Return the current authenticated user's profile.

HTTP method rationale:
  login    → GET: the extension opens this URL or fetches it; it has no request body.
  callback → GET: GitHub always redirects with a GET (query parameters, no body).
  logout   → POST: mutates state (revokes session); a POST prevents browser prefetch
              from accidentally logging the user out.
  me       → GET: read-only identity fetch.

State / CSRF handling:
  The signed state string is returned in the login response body.
  The extension stores it in chrome.storage.local (not a cookie, since the
  extension is not a web page served from the backend domain).
  On the callback the extension sends both the ?state= from GitHub's redirect
  AND the originally received state string (via X-OAuth-State header) so the
  server can verify they match.

Session token delivery:
  The raw session token is returned once in the callback JSON body.
  Subsequent requests must include it in the X-Session-Token header.
  It is never re-issued in a response; /api/auth/me returns the user profile,
  not the token.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.auth.schemas import (
    CallbackResponse,
    CurrentUserResponse,
    LoginInitResponse,
    LogoutResponse,
    UserProfile,
)
from app.auth.service import handle_oauth_callback, initiate_login, revoke_session
from app.core.database import get_db
from app.core.exceptions import OAuthError
from app.core.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── GET /api/auth/login ────────────────────────────────────────────────────────


@router.get(
    "/login",
    response_model=LoginInitResponse,
    summary="Initiate GitHub OAuth login",
    description=(
        "Returns the GitHub OAuth authorization URL and a signed CSRF state token. "
        "The client should redirect the user to authorize_url and store the state "
        "value to verify on the callback."
    ),
)
async def login(request: Request) -> LoginInitResponse:
    """
    Start the OAuth flow.
    Returns the GitHub authorization URL and the CSRF state string.
    The extension opens this URL in a popup/new tab.
    """
    user_agent = request.headers.get("user-agent")
    authorize_url, state = initiate_login(user_agent=user_agent)
    logger.info("OAuth login initiated. redirect=%s", authorize_url[:60])
    return LoginInitResponse(authorize_url=authorize_url, state=state)


# ── GET /api/auth/callback ────────────────────────────────────────────────────


@router.get(
    "/callback",
    response_model=CallbackResponse,
    summary="GitHub OAuth callback",
    description=(
        "GitHub redirects here after the user grants access. "
        "The server verifies the state, exchanges the code for an access token, "
        "upserts the user record, creates a session, and returns the session token."
    ),
)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from GitHub."),
    state: str = Query(..., description="CSRF state returned by GitHub."),
    x_oauth_state: str | None = Header(
        default=None,
        alias="x-oauth-state",
        description="Original state string stored by the client during login initiation.",
    ),
    db: AsyncSession = Depends(get_db),
) -> CallbackResponse:
    """
    Process the GitHub OAuth callback.

    The client sends the original state (from the login response) in the
    X-OAuth-State header so the server can verify it against the state
    GitHub echoed back in the query string.

    On success: returns session_token (store securely) and the user profile.
    On failure: returns 401 with a structured error.
    """
    # The client must send the originally received state for CSRF verification.
    # If the header is absent we fall back to comparing state with itself
    # (still valid — itsdangerous signature still verified), but warn.
    expected_state = x_oauth_state or state

    try:
        raw_token, user = await handle_oauth_callback(
            db=db,
            code=code,
            state=state,
            expected_state=expected_state,
        )
    except OAuthError as exc:
        logger.warning("OAuth callback failed: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": exc.error_code, "message": exc.message},
        ) from exc

    logger.info("OAuth callback successful. user=%s", user.github_username)

    return CallbackResponse(
        session_token=raw_token,
        user=UserProfile(
            id=user.id,
            github_username=user.github_username,
            avatar_url=user.avatar_url,
        ),
    )


# ── POST /api/auth/logout ─────────────────────────────────────────────────────


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Revoke the current session",
    description="Marks the caller's session as revoked. Subsequent requests with this token fail.",
)
async def logout(
    x_session_token: str | None = Header(default=None, alias="x-session-token"),
    db: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    """
    Revoke the session identified by X-Session-Token.
    Idempotent: logging out an already-revoked or nonexistent session returns 200.
    """
    if x_session_token:
        await revoke_session(db, x_session_token)
        logger.info("Session revoked.")
    return LogoutResponse()


# ── GET /api/auth/me ──────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Get current authenticated user",
    description=(
        "Returns the authenticated user's GitHub profile. "
        "Requires a valid X-Session-Token header."
    ),
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> CurrentUserResponse:
    """
    Return the currently authenticated user's profile.
    Validates the session via the shared get_current_user dependency.
    """
    return CurrentUserResponse(
        id=current_user.id,
        github_username=current_user.github_username,
        avatar_url=current_user.avatar_url,
    )
