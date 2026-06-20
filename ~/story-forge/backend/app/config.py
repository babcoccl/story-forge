"""Application configuration loaded from environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings sourced from .env file."""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/storyforge"

    # LLM / llama.cpp
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    default_model: str = "qwen3-27b"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.8

    # Pipeline
    max_combination_retries: int = 5
    bundle_roles: list[str] = [
        "protagonist",
        "antagonist",
        "primary_setting",
        "main_activity",
        "plot_driver",
        "theme",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()