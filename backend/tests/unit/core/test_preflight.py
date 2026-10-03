import pytest
from cryptography.fernet import Fernet

from app.core.preflight import (
    check_production_cors,
    validate_encryption_key,
    validate_fernet_key,
    validate_secret,
)


def test_validate_secret_missing():
    assert validate_secret("")[0] is False
    assert validate_secret(None)[0] is False


def test_validate_secret_length():
    # 31 chars
    assert validate_secret("a" * 30 + "b")[1] == "UNSAFE DEFAULT"
    # 32 chars
    assert validate_secret("a" * 31 + "b")[1] == "PASS"


def test_validate_secret_repeated():
    assert validate_secret("a" * 32)[1] == "UNSAFE DEFAULT"


def test_validate_secret_placeholder():
    assert validate_secret("your_shared_secret_here")[1] == "UNSAFE DEFAULT"


def test_validate_secret_weak_word():
    assert validate_secret("changeme")[1] == "UNSAFE DEFAULT"
    assert validate_secret("SECRET")[1] == "UNSAFE DEFAULT"
    assert validate_secret("password")[1] == "UNSAFE DEFAULT"


def test_validate_secret_substring_allowed():
    # Long value containing "secret" as a substring is NOT rejected
    long_secret = "a" * 16 + "secret" + "b" * 16
    assert validate_secret(long_secret)[1] == "PASS"


def test_cors_valid():
    assert check_production_cors(["chrome-extension://abcdefghijklmnopqrstuvwxyz123456"])[0] is True


def test_cors_missing():
    assert check_production_cors([])[0] is False


def test_cors_wildcard():
    assert check_production_cors(["*"])[0] is False


def test_cors_localhost():
    assert (
        check_production_cors(
            ["http://localhost:3000", "chrome-extension://abcdefghijklmnopqrstuvwxyz123456"]
        )[0]
        is False
    )


def test_cors_placeholder():
    assert check_production_cors(["chrome-extension://your-extension-id"])[0] is False


def test_cors_missing_extension():
    assert check_production_cors(["https://example.com"])[0] is False


def test_validate_secret_custom_length():
    assert validate_secret("a" * 19 + "b", min_length=20)[1] == "PASS"


# ── Fernet-format validation (separate from generic secret validation) ──────────


def test_fernet_valid_key_passes():
    key = Fernet.generate_key().decode()
    assert validate_fernet_key(key) == (True, "PASS")
    assert validate_encryption_key(key) == (True, "PASS")


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-fernet-key-but-long-enough-to-pass-generic-secret-checks",
        "abcdefghijklmnopqrstuvwxyz0123456789ABCD",  # 40 chars, not valid base64 of 32 bytes
        "A" * 43,  # wrong padding / length
    ],
)
def test_fernet_invalid_value_fails(bad):
    ok, status = validate_fernet_key(bad)
    assert ok is False
    assert status.startswith("INVALID FORMAT")
    assert validate_encryption_key(bad)[0] is False


def test_fernet_missing_value_handled():
    assert validate_fernet_key("") == (False, "MISSING")
    assert validate_fernet_key(None) == (False, "MISSING")
    assert validate_encryption_key("") == (False, "MISSING")


def test_encryption_key_still_runs_generic_checks_first():
    # Short value keeps the generic reason code rather than the Fernet one.
    assert validate_encryption_key("short") == (False, "UNSAFE DEFAULT")
    assert validate_encryption_key("your_fernet_key_here") == (False, "UNSAFE DEFAULT")


def test_fernet_failure_does_not_leak_key_value():
    bad = "this-is-a-sensitive-looking-value-that-is-not-fernet"
    assert bad not in validate_fernet_key(bad)[1]
