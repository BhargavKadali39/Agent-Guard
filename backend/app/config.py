"""Application configuration.

All runtime configuration comes from environment variables (or a local ``.env`` file).
Nothing security-sensitive is hardcoded: API keys are empty by default, and the JWT
secret is generated at startup for development/test runs when not provided.
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

INSECURE_SECRET_PREFIXES = ("change-me", "dev-only", "insecure", "secret", "password")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General -----------------------------------------------------------------
    app_name: str = "AgentGuard"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    # --- Database ----------------------------------------------------------------
    # SQLite is the zero-setup local default; PostgreSQL is used by docker-compose.
    database_url: str = "sqlite:///./agentguard.db"
    db_echo: bool = False

    # --- Authentication ----------------------------------------------------------
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # Comma-separated list of allowed browser origins (only needed when the frontend
    # talks to the API directly instead of through the Next.js rewrite proxy).
    cors_origins: str = "http://localhost:3000"

    # --- Demo data ---------------------------------------------------------------
    seed_demo_data: bool = True
    # Also run a handful of sample workflows at startup so dashboards show real records.
    seed_sample_workflows: bool = True
    # Local-development-only password shared by the seeded demo users.
    demo_user_password: str = "agentguard-demo"

    # --- AI provider -------------------------------------------------------------
    ai_provider: Literal["mock", "anthropic", "openai_compatible"] = "mock"
    # The deterministic mock can simulate a model that *complies* with injected
    # instructions (so the backend defenses are exercised) or one that resists them.
    mock_injection_behavior: Literal["comply", "resist"] = "comply"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 30.0
    ai_max_tokens: int = 1024

    # --- Workflow behaviour ------------------------------------------------------
    approval_expiry_hours: int = 72
    force_review_on_injection: bool = True
    low_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    max_proposed_tool_calls: int = 5
    tool_max_attempts: int = Field(default=3, ge=1, le=10)
    tool_retry_backoff_seconds: float = 0.05
    auto_recover_on_startup: bool = True
    # How long a worker's exclusive claim on a workflow lasts before another worker may
    # take over (protects against a crashed worker holding a workflow forever).
    workflow_lease_seconds: int = Field(default=60, ge=5, le=3600)
    simulated_gateway_latency_ms: int = 0

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value}")
        return value

    @model_validator(mode="after")
    def _validate_secrets(self) -> Settings:
        if self.environment == "production":
            if len(self.jwt_secret) < 32 or self.jwt_secret.lower().startswith(
                INSECURE_SECRET_PREFIXES
            ):
                raise ValueError(
                    "JWT_SECRET must be set to a strong random value (>= 32 chars) in production"
                )
            if self.seed_demo_data:
                logger.warning(
                    "SEED_DEMO_DATA is enabled in production; demo users use a shared password"
                )
        elif not self.jwt_secret:
            # Development/test convenience: tokens are invalidated on every restart.
            object.__setattr__(self, "jwt_secret", secrets.token_urlsafe(48))
            logger.warning("JWT_SECRET not set; generated an ephemeral secret for this process")
        if self.ai_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        if self.ai_provider == "openai_compatible" and not self.openai_api_key:
            raise ValueError("AI_PROVIDER=openai_compatible requires OPENAI_API_KEY")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
