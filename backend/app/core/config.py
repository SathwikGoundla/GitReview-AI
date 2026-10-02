"""
GitReview AI — Core Configuration
Loads all settings from environment variables. No secrets in code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = Field(default="development")
    debug: bool = Field(default=False)
    allowed_origins: list[str] = Field(default=["http://localhost:3000"])

    # --- Database ---
    database_url: str = Field(default="postgresql+asyncpg://localhost/gitreview_ai")
    database_url_sync: str = Field(default="postgresql://localhost/gitreview_ai")

    # --- GitHub OAuth ---
    github_client_id: str = Field(default="")
    github_client_secret: str = Field(default="")
    github_redirect_uri: str = Field(default="http://localhost:8000/api/auth/callback")
    github_api_base: str = Field(default="https://api.github.com")
    github_oauth_base: str = Field(default="https://github.com")

    # --- Session / Security ---
    encryption_key: str = Field(default="")  # Fernet key, base64-encoded 32 bytes
    state_secret: str = Field(default="")  # itsdangerous signing key
    session_expiry_hours: int = Field(default=24)

    # --- Google Gemini ---
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")
    gemini_timeout_seconds: int = Field(default=60)
    gemini_max_retries: int = Field(default=2)

    # --- Risk Engine ---
    max_pr_lines: int = Field(default=3000)
    max_pr_bytes: int = Field(default=1024 * 1024)  # 1 MB
    # Configurable path patterns for sensitive-path detection
    sensitive_path_patterns: list[str] = Field(
        default=[
            "auth/",
            "authentication/",
            "authorization/",
            "payment/",
            "payments/",
            "billing/",
            "migrations/",
            "migration/",
            "security/",
            "crypto/",
            "secrets/",
            "admin/",
            "config/",
            "settings/",
        ]
    )
    risk_size_medium_lines: int = Field(default=100)
    risk_size_high_lines: int = Field(default=500)
    risk_size_critical_lines: int = Field(default=1000)

    # --- Confidence Scoring ---
    confidence_cold_start_cap: int = Field(default=85)
    confidence_min_feedback_samples: int = Field(default=20)

    # --- Reviewer Recommendation ---
    reviewer_min_evidence_threshold: float = Field(default=0.05)
    reviewer_codeowners_weight: float = Field(default=0.6)
    reviewer_review_history_weight: float = Field(default=0.3)
    reviewer_commit_history_weight: float = Field(default=0.1)

    # --- GitHub Actions Integration ---
    # Shared secret for authenticating GitHub Actions workflow requests.
    # Each deployment should use a random secret stored in GitHub repository Secrets
    # (GITREVIEW_SHARED_SECRET) and in the backend's Render environment variables.
    # An empty string disables the Actions endpoint in production.
    actions_shared_secret: str = Field(default="")

    # --- Retention ---
    analysis_retention_days: int = Field(default=90)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    @field_validator("sensitive_path_patterns", mode="before")
    @classmethod
    def split_patterns(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",")]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
