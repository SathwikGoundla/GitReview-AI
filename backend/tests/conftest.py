"""
GitReview AI — pytest configuration.

Sets required environment variables before any module is imported,
so tests work without a real .env file.
"""

from __future__ import annotations

import os

# Minimal env vars needed by Settings — must be set before any app import
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("STATE_SECRET", "test-state-secret-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("GEMINI_API_KEY", "fake-key-for-tests")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/gitreview_ai_test",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://postgres:password@localhost:5432/gitreview_ai_test",
)
os.environ.setdefault("GITHUB_CLIENT_ID", "fake-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "fake-client-secret")

import pytest


@pytest.fixture(autouse=True)
def clear_settings_cache():
    from app.core.config import get_settings

    get_settings.cache_clear()
