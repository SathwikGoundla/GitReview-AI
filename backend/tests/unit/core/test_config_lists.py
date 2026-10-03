"""List-valued settings must parse from env in JSON and comma-separated forms."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

EXT = "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef"


def _settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_allowed_origins_comma_separated(monkeypatch):
    s = _settings(monkeypatch, ALLOWED_ORIGINS=f"http://localhost:3000, {EXT}")
    assert s.allowed_origins == ["http://localhost:3000", EXT]


def test_allowed_origins_json_list(monkeypatch):
    s = _settings(monkeypatch, ALLOWED_ORIGINS=f'["http://localhost:3000","{EXT}"]')
    assert s.allowed_origins == ["http://localhost:3000", EXT]


def test_allowed_origins_single_value(monkeypatch):
    assert _settings(monkeypatch, ALLOWED_ORIGINS=EXT).allowed_origins == [EXT]


def test_empty_items_dropped(monkeypatch):
    s = _settings(monkeypatch, ALLOWED_ORIGINS=f"{EXT},,")
    assert s.allowed_origins == [EXT]


def test_sensitive_path_patterns_both_formats(monkeypatch):
    assert _settings(
        monkeypatch, SENSITIVE_PATH_PATTERNS="auth/, payments/"
    ).sensitive_path_patterns == [
        "auth/",
        "payments/",
    ]
    assert _settings(
        monkeypatch, SENSITIVE_PATH_PATTERNS='["auth/","db/"]'
    ).sensitive_path_patterns == [
        "auth/",
        "db/",
    ]


@pytest.mark.parametrize("bad", ['["unterminated', '["a", 1]', "[1,2]"])
def test_invalid_json_list_fails_clearly(monkeypatch, bad):
    monkeypatch.setenv("ALLOWED_ORIGINS", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_default_unchanged(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert Settings(_env_file=None).allowed_origins == ["http://localhost:3000"]


def test_wildcard_still_visible_to_preflight(monkeypatch):
    # Parsing must not sanitise away '*'; production CORS validation still sees it.
    from app.core.preflight import check_production_cors

    s = _settings(monkeypatch, ALLOWED_ORIGINS="*")
    assert s.allowed_origins == ["*"]
    assert check_production_cors(s.allowed_origins)[0] is False
