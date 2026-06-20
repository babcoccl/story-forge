# Judge schemas — JudgeRequest and JudgeVerdict for Phase 4

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class BundleItem(BaseModel):
    """A single component in a judged bundle (mirrors sampler output)."""

    role: str
    component_id: int
    name: str
    tags: List[str] = []
    rarity_weight: float = 1.0


class JudgeRequest(BaseModel):
    """Request to the judge agent to evaluate a component bundle."""

    bundle: List[BundleItem]
    attempt_number: int = 1


class JudgeVerdict(BaseModel):
    """Structured verdict returned by the judge agent."""

    approved: bool
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str
    weak_roles: List[str] = []
    suggested_avoid_tags: List[str] = []
    suggested_require_tags: List[str] = []