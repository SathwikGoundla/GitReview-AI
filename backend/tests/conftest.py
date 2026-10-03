"""
GitReview AI — pytest configuration.

Sets required environment variables before any module is imported,
so tests work without a real .env file.
"""

from __future__ import annotations

import os

import pytest

# Test isolation: these values are FORCED (not setdefault) so that a real
# DATABASE_URL / API key / secret exported in the developer's shell can never be
# picked up by the test suite and reach a real Supabase DB or external service.
# (A real backend/.env is also overridden, because process env beats dotenv.)
_TEST_ENV = {
    "APP_ENV": "test",
    "DEBUG": "false",
    "STATE_SECRET": "test-state-secret-not-for-production",
    "ENCRYPTION_KEY": "",
    "GEMINI_API_KEY": "fake-key-for-tests",
    "DATABASE_URL": "postgresql+asyncpg://postgres:password@localhost:5432/gitreview_ai_test",
    "DATABASE_URL_SYNC": "postgresql://postgres:password@localhost:5432/gitreview_ai_test",
    "GITHUB_CLIENT_ID": "fake-client-id",
    "GITHUB_CLIENT_SECRET": "fake-client-secret",
    "ACTIONS_SHARED_SECRET": "fake-actions-shared-secret-for-tests",
}
os.environ.update(_TEST_ENV)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    from app.core.config import get_settings

    get_settings.cache_clear()
