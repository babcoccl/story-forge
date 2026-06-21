"""Pydantic schemas for story request/response validation.

Schemas:
  - ScenePlan, ChapterPlan, StoryPlan  (LLM planner output)
  - StoryCreateRequest                 (API input)
  - StoryResponse                      (API output)
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Planner Output Schemas
# ---------------------------------------------------------------------------

class ScenePlan(BaseModel):
    """One scene within a chapter."""

    scene_number: int = Field(..., description="1-based scene number within the chapter")
    goal: str = Field(..., description="What the scene must accomplish narratively")
    conflict: str = Field(..., description="The tension or obstacle in the scene")
    outcome: str = Field(..., description="How the scene ends and what it sets up")
    setting_note: str = Field(
        ..., description="Which setting component is active in this scene"
    )
    word_count_target: int = Field(
        ..., description="Suggested word count for this scene"
    )


class ChapterPlan(BaseModel):
    """One chapter in the story plan."""

    chapter_number: int = Field(..., description="1-based chapter number")
    title: str = Field(..., description="Chapter title")
    summary: str = Field(..., description="2-3 sentence chapter summary")
    scenes: list[ScenePlan] = Field(
        ..., min_length=3, max_length=5, description="3-5 scenes per chapter"
    )


class StoryPlan(BaseModel):
    """Complete structured story plan produced by PlannerAgent."""

    title: str = Field(..., description="Compelling story title")
    logline: str = Field(..., description="One-sentence premise")
    synopsis: str = Field(..., description="3-5 sentence full synopsis")
    themes: list[str] = Field(
        ..., description="Active theme tags drawn from component bundle"
    )
    chapter_count: int = Field(..., description="Number of chapters in the plan")
    chapters: list[ChapterPlan] = Field(..., description="List of chapter plans")
    story_bible: dict[str, Any] = Field(
        ...,
        description="Keys: characters, world_state, tone, pacing_notes",
    )


# ---------------------------------------------------------------------------
# API Request / Response Schemas
# ---------------------------------------------------------------------------

class StoryCreateRequest(BaseModel):
    """Request body for creating a new story."""

    mode: Literal["standalone", "continuation"] = "standalone"
    seed: str | None = None
    overrides: dict[str, str] = Field(default_factory=dict)
    target_word_count: int = 15000
    parent_story_id: UUID | None = None


class StoryResponse(BaseModel):
    """Response body for story endpoints."""

    model_config = {"from_attributes": True}

    id: UUID
    title: str | None = None
    mode: str
    status: str
    generation_seed: str | None = None
    synopsis: str | None = None
    target_word_count: int
    story_bible: dict[str, Any] | None = None
    chapter_count: int = Field(
        ..., description="Computed from len(chapters)"
    )
    scene_count: int = Field(
        ..., description="Computed from sum of scenes per chapter"
    )
    created_at: datetime