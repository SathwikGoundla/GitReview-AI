"""
GitReview AI — Security Utilities

- Fernet envelope encryption for OAuth tokens at rest
- SHA-256 salted hashing for session tokens (only hash stored in DB)
- CSRF state generation/verification via itsdangerous

Design note (LLD Part O):
  The raw OAuth token is encrypted before writing to users.encrypted_access_token.
  The encryption key lives in Render's environment config, never in the DB.
  Session tokens are stored as salted SHA-256 hashes only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings
from app.core.exceptions import AuthError, OAuthError

# ── Fernet token encryption ────────────────────────────────────────────────────


def _get_fernet() -> Fernet:
    """Return a Fernet instance keyed from the environment."""
    settings = get_settings()
    key = settings.encryption_key
    if not key:
        raise RuntimeError("ENCRYPTION_KEY environment variable is not set.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext_token: str) -> str:
    """Encrypt an OAuth access token for storage. Returns ciphertext string."""
    f = _get_fernet()
    return f.encrypt(plaintext_token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored OAuth access token. Raises AuthError on tamper/expiry."""
    try:
        f = _get_fernet()
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise AuthError("Stored access token is invalid or has been tampered with.") from exc


# ── Session token hashing ──────────────────────────────────────────────────────


def generate_session_token() -> str:
    """Generate a cryptographically secure opaque session token."""
    return secrets.token_urlsafe(32)


def hash_session_token(raw_token: str) -> str:
    """
    Return a salted SHA-256 hash of the session token for DB storage.
    A static application-level pepper is mixed in to prevent rainbow tables.
    Only the hash is stored; the raw token exists only in transit and in
    the extension's chrome.storage.local.
    """
    settings = get_settings()
    pepper = settings.state_secret.encode() or b"gitreview-pepper"
    return hmac.new(pepper, raw_token.encode(), hashlib.sha256).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


# ── CSRF state for OAuth ───────────────────────────────────────────────────────


def _get_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    if not settings.state_secret:
        raise RuntimeError("STATE_SECRET environment variable is not set.")
    return URLSafeTimedSerializer(settings.state_secret, salt="oauth-state")


def generate_oauth_state(user_agent_fingerprint: str | None = None) -> str:
    """
    Generate a signed, time-limited state parameter for GitHub OAuth.
    The state encodes a nonce plus optional browser fingerprint.
    """
    s = _get_serializer()
    payload = {
        "nonce": secrets.token_hex(16),
        "fp": user_agent_fingerprint or "",
    }
    return s.dumps(payload)


def verify_oauth_state(state: str, max_age_seconds: int = 600) -> dict:
    """
    Verify the OAuth state parameter. Raises OAuthError on invalid/expired state.
    Returns the payload dict on success.
    """
    s = _get_serializer()
    try:
        return s.loads(state, max_age=max_age_seconds)
    except SignatureExpired as exc:
        raise OAuthError("OAuth state parameter has expired. Please retry login.") from exc
    except BadSignature as exc:
        raise OAuthError("OAuth state parameter is invalid or has been tampered with.") from exc


# ── Shared-secret validation for GitHub Actions ────────────────────────────────


def validate_actions_secret(provided: str, expected: str) -> None:
    """
    Validate the per-repository shared secret sent by a GitHub Actions workflow.
    Uses constant-time comparison to prevent timing attacks.
    Raises AuthError if the secret does not match.
    """
    if not constant_time_compare(provided, expected):
        raise AuthError("Invalid or missing GitHub Actions shared secret.")
