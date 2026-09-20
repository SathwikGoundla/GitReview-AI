"""Unit tests for app.core.security."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-state-secret-for-unit-tests-only")


def _get_valid_fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


class TestSessionTokenHashing:
    def test_hash_produces_string(self):
        from app.core.security import hash_session_token

        result = hash_session_token("my-raw-token")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest

    def test_same_token_same_hash(self):
        from app.core.security import hash_session_token

        assert hash_session_token("abc") == hash_session_token("abc")

    def test_different_tokens_different_hashes(self):
        from app.core.security import hash_session_token

        assert hash_session_token("abc") != hash_session_token("def")

    def test_generate_session_token_is_urlsafe(self):
        from app.core.security import generate_session_token

        token = generate_session_token()
        assert isinstance(token, str)
        assert len(token) >= 32
        # URL-safe means no +/ characters
        import re

        assert re.match(r"^[A-Za-z0-9_\-]+$", token)

    def test_generate_session_token_is_unique(self):
        from app.core.security import generate_session_token

        tokens = {generate_session_token() for _ in range(50)}
        assert len(tokens) == 50


class TestConstantTimeCompare:
    def test_equal_strings(self):
        from app.core.security import constant_time_compare

        assert constant_time_compare("abc", "abc") is True

    def test_unequal_strings(self):
        from app.core.security import constant_time_compare

        assert constant_time_compare("abc", "def") is False

    def test_empty_strings(self):
        from app.core.security import constant_time_compare

        assert constant_time_compare("", "") is True


class TestOAuthState:
    def test_generate_and_verify_state(self):
        from app.core.security import generate_oauth_state, verify_oauth_state

        state = generate_oauth_state()
        payload = verify_oauth_state(state)
        assert "nonce" in payload
        assert isinstance(payload["nonce"], str)

    def test_verify_tampered_state_raises(self):
        from app.core.exceptions import OAuthError
        from app.core.security import generate_oauth_state, verify_oauth_state

        state = generate_oauth_state()
        tampered = state[:-3] + "XXX"
        with pytest.raises(OAuthError):
            verify_oauth_state(tampered)

    def test_verify_expired_state_raises(self):
        from app.core.exceptions import OAuthError
        from app.core.security import generate_oauth_state, verify_oauth_state

        state = generate_oauth_state()
        # max_age_seconds=-1 forces expiry regardless of when the token was signed
        with pytest.raises(OAuthError):
            verify_oauth_state(state, max_age_seconds=-1)

    def test_state_with_fingerprint(self):
        from app.core.security import generate_oauth_state, verify_oauth_state

        state = generate_oauth_state(user_agent_fingerprint="Mozilla/5.0")
        payload = verify_oauth_state(state)
        assert payload["fp"] == "Mozilla/5.0"


class TestFernetEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        key = _get_valid_fernet_key()
        os.environ["ENCRYPTION_KEY"] = key
        # Reset settings cache
        from app.core.config import get_settings

        get_settings.cache_clear()

        from app.core.security import decrypt_token, encrypt_token

        plaintext = "gho_test_token_12345"
        ciphertext = encrypt_token(plaintext)
        assert ciphertext != plaintext
        assert decrypt_token(ciphertext) == plaintext

    def test_ciphertext_is_different_each_time(self):
        key = _get_valid_fernet_key()
        os.environ["ENCRYPTION_KEY"] = key
        from app.core.config import get_settings

        get_settings.cache_clear()

        from app.core.security import encrypt_token

        c1 = encrypt_token("same-token")
        c2 = encrypt_token("same-token")
        assert c1 != c2  # Fernet uses a random IV

    def test_decrypt_tampered_raises(self):
        key = _get_valid_fernet_key()
        os.environ["ENCRYPTION_KEY"] = key
        from app.core.config import get_settings

        get_settings.cache_clear()

        from app.core.exceptions import AuthError
        from app.core.security import decrypt_token

        with pytest.raises(AuthError):
            decrypt_token("not-valid-fernet-ciphertext")
