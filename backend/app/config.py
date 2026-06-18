import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

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
    max_scene_retries: int = 3
    max_combination_retries: int = 5
    target_words_per_scene: int = 1500
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()