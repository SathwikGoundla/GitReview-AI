"""
GitReview AI — Typed Exception Hierarchy
Every failure mode has a named exception. No bare Exception raises.
"""

from __future__ import annotations

# ── Base ───────────────────────────────────────────────────────────────────────


class GitReviewError(Exception):
    """Root exception for all GitReview AI errors."""

    http_status: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# ── Authentication / Authorization ─────────────────────────────────────────────


class AuthError(GitReviewError):
    http_status = 401
    error_code = "auth_error"


class SessionExpiredError(AuthError):
    error_code = "session_expired"


class SessionRevokedError(AuthError):
    error_code = "session_revoked"


class OAuthError(AuthError):
    error_code = "oauth_error"


class AuthorizationError(GitReviewError):
    http_status = 403
    error_code = "authorization_error"


class RepositoryAccessDeniedError(AuthorizationError):
    error_code = "repository_access_denied"


# ── GitHub Integration ──────────────────────────────────────────────────────────


class GitHubError(GitReviewError):
    http_status = 502
    error_code = "github_error"


class GitHubRateLimitError(GitHubError):
    http_status = 429
    error_code = "github_rate_limit"


class GitHubNotFoundError(GitHubError):
    http_status = 404
    error_code = "github_not_found"


class GitHubPermissionError(GitHubError):
    http_status = 403
    error_code = "github_permission_denied"


# ── AI Provider ────────────────────────────────────────────────────────────────


class AIProviderError(GitReviewError):
    http_status = 502
    error_code = "ai_provider_error"


class AITimeoutError(AIProviderError):
    error_code = "ai_timeout"


class AIRateLimitError(AIProviderError):
    http_status = 429
    error_code = "ai_rate_limit"


class AIValidationError(GitReviewError):
    http_status = 422
    error_code = "ai_validation_error"


# ── Analysis ───────────────────────────────────────────────────────────────────


class AnalysisError(GitReviewError):
    error_code = "analysis_error"


class AnalysisDegradedError(AnalysisError):
    """Pipeline completed but with degraded AI output (deterministic-only)."""

    error_code = "analysis_degraded"


class PromptTooLargeError(AnalysisError):
    error_code = "prompt_too_large"


class PRTooLargeError(AnalysisError):
    http_status = 413
    error_code = "PR_TOO_LARGE"

# ── Database ───────────────────────────────────────────────────────────────────


class DatabaseError(GitReviewError):
    error_code = "database_error"


# ── Validation ─────────────────────────────────────────────────────────────────


class ValidationError(GitReviewError):
    http_status = 422
    error_code = "validation_error"


# ── Repository / PR ────────────────────────────────────────────────────────────


class RepositoryNotFoundError(GitReviewError):
    http_status = 404
    error_code = "repository_not_found"


class PullRequestNotFoundError(GitReviewError):
    http_status = 404
    error_code = "pull_request_not_found"


# ── GitHub Actions Integration ─────────────────────────────────────────────────


class ActionsAuthError(GitReviewError):
    """Raised when the GitHub Actions shared secret is missing or invalid."""

    http_status = 401
    error_code = "actions_auth_error"
