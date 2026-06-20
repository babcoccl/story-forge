"""Pydantic schemas for the Sampler Service (Phase 3)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SampleRequest(BaseModel):
    """Request to sample a component bundle."""

    mode: Literal["standalone", "continuation"] = "standalone"
    seed: str | None = None
    overrides: dict[str, str] = {}
    target_word_count: int = 15000
    hint_avoid_tags: list[str] = []
    hint_require_tags: list[str] = []


class BundleItem(BaseModel):
    """One component in a sampled bundle."""

    role: str
    component_id: UUID
    slug: str
    name: str
    component_type: str
    tags: list[str]
    compatibility_tags: list[str]
    description: str
    prompt_fragment: str | None = None


class SampleResult(BaseModel):
    """Result of a sampling operation."""

    seed: str
    bundle: list[BundleItem]
    constraint_violations: list[str]
    attempts: int
    score: float