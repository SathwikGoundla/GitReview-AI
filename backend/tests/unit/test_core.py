"""Unit tests for app.core.config and app.core.exceptions."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")


class TestSettings:
    def test_settings_loads_with_defaults(self):
        from app.core.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert s.app_env in ("development", "production", "test")
        assert isinstance(s.session_expiry_hours, int)
        assert s.session_expiry_hours > 0

    def test_sensitive_path_patterns_is_list(self):
        from app.core.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s.sensitive_path_patterns, list)
        assert len(s.sensitive_path_patterns) > 0

    def test_confidence_settings_have_valid_ranges(self):
        from app.core.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert 0 < s.confidence_cold_start_cap <= 100
        assert s.confidence_min_feedback_samples > 0

    def test_reviewer_weights_sum_to_one(self):
        from app.core.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        total = (
            s.reviewer_codeowners_weight
            + s.reviewer_review_history_weight
            + s.reviewer_commit_history_weight
        )
        assert abs(total - 1.0) < 0.001, f"Reviewer weights sum to {total}, not 1.0"

    def test_risk_size_thresholds_ordered(self):
        from app.core.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert s.risk_size_medium_lines < s.risk_size_high_lines < s.risk_size_critical_lines

    def test_is_production_false_by_default(self):
        from app.core.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert s.is_production is False


class TestExceptionHierarchy:
    def test_all_errors_inherit_from_gitreview_error(self):
        from app.core.exceptions import (
            AIProviderError,
            AIValidationError,
            AuthError,
            GitHubError,
            GitReviewError,
            RepositoryAccessDeniedError,
        )

        for exc_class in (
            AuthError,
            AIProviderError,
            AIValidationError,
            GitHubError,
            RepositoryAccessDeniedError,
        ):
            assert issubclass(exc_class, GitReviewError)

    def test_auth_error_has_401_status(self):
        from app.core.exceptions import AuthError

        assert AuthError.http_status == 401

    def test_authorization_error_has_403_status(self):
        from app.core.exceptions import AuthorizationError

        assert AuthorizationError.http_status == 403

    def test_github_rate_limit_has_429_status(self):
        from app.core.exceptions import GitHubRateLimitError

        assert GitHubRateLimitError.http_status == 429

    def test_exception_carries_message(self):
        from app.core.exceptions import AnalysisError

        exc = AnalysisError("something went wrong", detail="extra info")
        assert exc.message == "something went wrong"
        assert exc.detail == "extra info"
        assert str(exc) == "something went wrong"

    def test_exception_can_be_raised_and_caught(self):
        from app.core.exceptions import AIValidationError, GitReviewError

        with pytest.raises(GitReviewError):
            raise AIValidationError("schema mismatch")


class TestLogging:
    def test_get_logger_returns_logger(self):
        import logging

        from app.core.logging import get_logger

        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"

    def test_log_event_scrubs_diff_field(self):
        """Fields named 'diff' or 'content' must not appear in log output."""
        import logging

        from app.core.logging import get_logger, log_event

        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = get_logger("test.scrub")
        handler = Capture()
        logger.addHandler(handler)

        log_event(
            logger,
            "test_event",
            {
                "analysis_id": "abc-123",
                "diff": "secret diff content",
                "file_content": "source code here",
                "risk_tier": "high",
            },
        )

        assert records
        msg = records[-1]
        assert "secret diff content" not in msg
        assert "source code here" not in msg
        assert "abc-123" in msg  # Non-sensitive field preserved
        assert "high" in msg  # Non-sensitive field preserved

    def test_log_event_preserves_safe_fields(self):
        import logging

        from app.core.logging import get_logger, log_event

        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = get_logger("test.safe")
        logger.addHandler(Capture())

        log_event(
            logger,
            "analysis_success",
            {
                "pull_request_id": "pr-456",
                "risk_tier": "medium",
                "latency_ms": 1200,
            },
        )
        msg = records[-1]
        assert "pr-456" in msg
        assert "medium" in msg
