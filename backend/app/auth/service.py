"""
GitReview AI — Authentication Service (LLD A.2 / B.1)

Owns the GitHub OAuth 2.0 flow and session issuance/validation/revocation.
All token storage and session hashing delegate to app.core.security.
All DB access goes through SQLAlchemy models — no raw SQL here.

Design decisions:
  - OAuth tokens are encrypted (Fernet) before storage; only ciphertext in DB.
  - Session tokens are stored as SHA-256 HMAC hashes; raw token is never written.
  - CSRF state is a signed, time-limited itsdangerous token.
  - get_or_create_user is an upsert on github_user_id (the true, immutable identity).
  - Sessions expire after settings.session_expiry_hours hours.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthError, OAuthError, SessionExpiredError, SessionRevokedError
from app.core.models import Session, User
from app.core.security import (
    decrypt_token,
    encrypt_token,
    generate_oauth_state,
    generate_session_token,
    hash_session_token,
    verify_oauth_state,
)

settings = get_settings()


# ── OAuth helpers ─────────────────────────────────────────────────────────────


def build_github_authorize_url(state: str) -> str:
    """
    Construct the GitHub OAuth authorization URL.
    The caller must already hold the signed CSRF state string.
    """
    params = (
        f"client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_redirect_uri}"
        f"&scope=repo%20read%3Auser"
        f"&state={state}"
    )
    return f"{settings.github_oauth_base}/login/oauth/authorize?{params}"


async def exchange_code_for_token(code: str) -> str:
    """
    Exchange a GitHub authorization code for an access token.
    Returns the raw plaintext access token (not yet encrypted).
    Raises OAuthError on failure.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.github_oauth_base}/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
        )

    if resp.status_code != 200:
        raise OAuthError(
            f"GitHub token exchange failed with HTTP {resp.status_code}.",
            detail=resp.text,
        )

    body = resp.json()

    if "error" in body:
        raise OAuthError(
            f"GitHub token exchange error: {body['error']}",
            detail=body.get("error_description"),
        )

    token = body.get("access_token")
    if not token:
        raise OAuthError("GitHub did not return an access_token in the response.")

    return token


async def fetch_github_user(access_token: str) -> dict:
    """
    Fetch the authenticated user's GitHub identity using their access token.
    Returns the raw GitHub user object (id, login, avatar_url, …).
    Raises OAuthError on failure.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{settings.github_api_base}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    if resp.status_code == 401:
        raise OAuthError("Access token was rejected by GitHub /user endpoint.")
    if resp.status_code != 200:
        raise OAuthError(
            f"GitHub /user request failed with HTTP {resp.status_code}.",
            detail=resp.text,
        )

    return resp.json()


# ── User upsert ───────────────────────────────────────────────────────────────


async def get_or_create_user(db: AsyncSession, github_user: dict, encrypted_token: str) -> User:
    """
    Upsert a User row keyed on github_user_id.
    If the user already exists, their token and username are refreshed.
    Returns the ORM User object.

    Design note: github_user_id is the immutable GitHub numeric identity.
    github_username (login) can change; we refresh it on every login.
    """
    github_id = github_user["id"]
    username = github_user.get("login", "")
    avatar_url = github_user.get("avatar_url")

    stmt = (
        pg_insert(User)
        .values(
            github_user_id=github_id,
            github_username=username,
            avatar_url=avatar_url,
            encrypted_access_token=encrypted_token,
            updated_at=datetime.now(UTC),
        )
        .on_conflict_do_update(
            index_elements=["github_user_id"],
            set_={
                "github_username": username,
                "avatar_url": avatar_url,
                "encrypted_access_token": encrypted_token,
                "updated_at": datetime.now(UTC),
            },
        )
        .returning(User)
    )

    result = await db.execute(stmt)
    await db.flush()  # materialise the RETURNING row

    user = result.scalars().first()
    if user is None:
        # Fallback: fetch by github_user_id (should not normally be needed)
        row = await db.execute(select(User).where(User.github_user_id == github_id))
        user = row.scalars().first()

    if user is None:
        raise AuthError("Failed to create or retrieve user after upsert.")

    return user


# ── Session lifecycle ─────────────────────────────────────────────────────────


async def create_session(db: AsyncSession, user_id: uuid.UUID) -> str:
    """
    Issue a new session for the given user.
    Returns the raw session token (to be returned to the client once only).
    Only the HMAC hash is persisted in the DB.
    """
    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.session_expiry_hours)

    session = Session(
        user_id=user_id,
        session_token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()

    return raw_token


async def validate_session(db: AsyncSession, raw_token: str) -> tuple[Session, User]:
    """
    Validate a raw session token. Returns (Session, User) on success.
    Raises SessionExpiredError, SessionRevokedError, or AuthError on failure.

    This is called on EVERY authenticated request (LLD A.2).
    """
    token_hash = hash_session_token(raw_token)

    result = await db.execute(
        select(Session, User)
        .join(User, Session.user_id == User.id)
        .where(Session.session_token_hash == token_hash)
    )
    row = result.first()

    if row is None:
        raise AuthError("Session not found. Please sign in again.")

    session, user = row

    now = datetime.now(UTC)

    if session.revoked_at is not None:
        raise SessionRevokedError("This session has been revoked. Please sign in again.")

    if session.expires_at < now:
        raise SessionExpiredError("Your session has expired. Please sign in again.")

    return session, user


async def revoke_session(db: AsyncSession, raw_token: str) -> None:
    """
    Revoke (logout) the session identified by raw_token.
    Idempotent — revoking an already-revoked or nonexistent session is a no-op.
    """
    token_hash = hash_session_token(raw_token)

    result = await db.execute(select(Session).where(Session.session_token_hash == token_hash))
    session = result.scalars().first()

    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.flush()


# ── High-level OAuth entry points ─────────────────────────────────────────────


def initiate_login(user_agent: str | None = None) -> tuple[str, str]:
    """
    Start the OAuth flow.
    Returns (authorize_url, state_string).
    The caller must store state in a short-lived cookie/storage and
    redirect the user to authorize_url.
    """
    state = generate_oauth_state(user_agent_fingerprint=user_agent)
    url = build_github_authorize_url(state)
    return url, state


async def handle_oauth_callback(
    db: AsyncSession,
    code: str,
    state: str,
    expected_state: str,
) -> tuple[str, User]:
    """
    Process the GitHub OAuth callback.
    1. Verify CSRF state.
    2. Exchange code for access token.
    3. Fetch GitHub user identity.
    4. Upsert the user record with encrypted token.
    5. Create a new session.
    Returns (raw_session_token, user).
    """
    # Step 1: CSRF verification
    if state != expected_state:
        raise OAuthError("OAuth state mismatch. Possible CSRF attempt.")

    try:
        verify_oauth_state(state)
    except OAuthError:
        raise

    # Step 2: Exchange code
    access_token = await exchange_code_for_token(code)

    # Step 3: Fetch GitHub identity
    github_user = await fetch_github_user(access_token)

    # Step 4: Encrypt token and upsert user
    encrypted = encrypt_token(access_token)
    user = await get_or_create_user(db, github_user, encrypted)

    # Step 5: Issue session
    raw_session_token = await create_session(db, user.id)

    return raw_session_token, user


async def get_current_user_from_token(db: AsyncSession, raw_token: str) -> User:
    """
    Convenience wrapper: validate session token and return the resolved User.
    Used by the FastAPI dependency (app/api/dependencies.py).
    """
    _session, user = await validate_session(db, raw_token)
    return user


def get_decrypted_token_for_user(user: User) -> str:
    """
    Decrypt and return the OAuth access token for a User.
    Used by the GitHub Integration Module when it needs to call the GitHub API
    on behalf of the authenticated user.
    """
    return decrypt_token(user.encrypted_access_token)
