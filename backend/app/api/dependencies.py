"""
GitReview AI — FastAPI Shared Dependencies (LLD A.1 / B.1)

get_current_user is the gateway-layer session validator.
It is injected into every authenticated endpoint via FastAPI's
Depends() mechanism.

Design notes:
  - Session token is expected in the X-Session-Token header.
    This keeps it out of the URL (no server logs leak) and out of the
    Authorization: Bearer header (avoids confusion with GitHub tokens).
  - On 401, a JSON error body matching ErrorResponse is returned so the
    extension can reliably parse the rejection and trigger re-auth.
  - Database session is a separate dependency (get_db) injected alongside;
    they are NOT nested to keep concerns separate.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import get_current_user_from_token
from app.core.database import get_db
from app.core.exceptions import AuthError, SessionExpiredError, SessionRevokedError
from app.core.models import User

# Header name used by the extension and GitHub Actions for the session token.
# Lowercase for FastAPI Header() (HTTP headers are case-insensitive).
SESSION_TOKEN_HEADER = "x-session-token"


async def get_current_user(
    x_session_token: str | None = Header(default=None, alias="x-session-token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency: resolve the X-Session-Token header to an authenticated User.

    Used as:
        current_user: User = Depends(get_current_user)

    Raises HTTP 401 if:
      - The header is absent
      - The token does not match any stored session hash
      - The session is revoked
      - The session is expired

    Returns the SQLAlchemy User ORM object on success.
    """
    if not x_session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_session_token",
                "message": "X-Session-Token header is required.",
            },
        )

    try:
        user = await get_current_user_from_token(db, x_session_token)
    except SessionExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "session_expired",
                "message": str(exc),
            },
        ) from exc
    except SessionRevokedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "session_revoked",
                "message": str(exc),
            },
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "auth_error",
                "message": str(exc),
            },
        ) from exc

    return user
