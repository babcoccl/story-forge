"""Application configuration loaded from .env file."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env path relative to project root (two levels up from this file)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=os.path.join(_PROJECT_ROOT, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    database_url_sync: str
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_api_key: str = "local"
    default_model: str = "qwen3-27b"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.8
    llm_context_window: int = 32768
    llm_timeout: float = 120.0
    max_scene_retries: int = 3
    max_combination_retries: int = 15
    prose_quality_threshold: float = 0.72
    max_scene_revisions: int = 2
    min_words_per_scene: int = 800
    log_level: str = "INFO"

    # Token cost estimation — set to $ per million tokens for cost display.
    # When 0.0 (default), cost display is hidden in the UI.
    cost_per_million_tokens: float = 0.0

    # CORS — comma-separated list of allowed origins.
    # Default permits the Next.js dev server and localhost variants.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse cors_origins string into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()