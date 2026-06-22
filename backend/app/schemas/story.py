"""Pydantic schemas for story request/response validation.

Schemas:
  - ScenePlan, ChapterPlan, StoryPlan  (LLM planner output)
  - StoryCreateRequest                 (API input)
  - StoryResponse                      (API output)
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Planner Output Schemas
# ---------------------------------------------------------------------------

class ScenePlan(BaseModel):
    """One scene within a chapter.

    model_config populate_by_name=True allows both the canonical field name
    and any registered alias to populate the field during parsing.

    Two model_validators handle LLM field-name drift for setting_note and
    word_count_target, which Qwen3 27B consistently aliases as
    setting_note_reference and word_count_allocation respectively.
    """

    model_config = {"populate_by_name": True}

    scene_number: int = Field(..., description="1-based scene number within the chapter")
    goal: str = Field(..., description="What the scene must accomplish narratively")
    conflict: str = Field(..., description="The tension or obstacle in the scene")
    outcome: str = Field(..., description="How the scene ends and what it sets up")

    setting_note: str | None = Field(
        None,
        description="Which setting component is active in this scene",
    )
    word_count_target: int | None = Field(
        None,
        description="Suggested word count for this scene",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        """Remap alternate field names the LLM may generate before validation.

        Handles known Qwen3 27B variants for setting_note and word_count_target.
        Runs before Pydantic field validation so remapped keys are treated as
        canonical field names.
        """
        if isinstance(data, dict):
            # setting_note variants — add new variants here as discovered
            for alt in (
                "setting_note_reference",
                "setting_note_desc",
                "setting_description",
                "setting",
            ):
                if alt in data and "setting_note" not in data:
                    data["setting_note"] = data[alt]

            # word_count_target variants — add new variants here as discovered
            for alt in (
                "word_count_allocation",
                "word_count",
                "target_word_count",
                "words",
                "word_target",
            ):
                if alt in data and "word_count_target" not in data:
                    data["word_count_target"] = data[alt]

        return data

    @model_validator(mode="after")
    def apply_defaults(self) -> "ScenePlan":
        """Apply fallback defaults if fields are still None after alias normalization.

        setting_note defaults to 'Primary setting' — a safe placeholder that
        SceneWriterAgent can use without error.

        word_count_target defaults to 1250 — the value the LLM was already
        computing (target_word_count / scenes_total at 15000 / 12 scenes).
        """
        if self.setting_note is None:
            self.setting_note = "Primary setting"
        if self.word_count_target is None:
            self.word_count_target = 1250
        return self


class ChapterPlan(BaseModel):
    """One chapter in the story plan."""

    chapter_number: int = Field(..., description="1-based chapter number")
    title: str | None = Field(None, description="Chapter title")
    summary: str = Field(..., description="2-3 sentence chapter summary")
    scenes: list[ScenePlan] = Field(
        ..., min_length=3, max_length=5, description="3-5 scenes per chapter"
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        """Remap alternate chapter field names the LLM may generate."""
        if isinstance(data, dict):
            # title variants
            for alt in ("chapter_title", "name", "heading", "chapter_name"):
                if alt in data and "title" not in data:
                    data["title"] = data[alt]
            # summary variants
            for alt in ("description", "overview", "chapter_summary", "synopsis"):
                if alt in data and "summary" not in data:
                    data["summary"] = data[alt]
        return data

    @model_validator(mode="after")
    def apply_defaults(self) -> "ChapterPlan":
        """Apply fallback if title still None after normalization."""
        if self.title is None:
            self.title = f"Chapter {self.chapter_number}"
        return self


class StoryPlan(BaseModel):
    """Complete structured story plan produced by PlannerAgent."""

    title: str = Field(..., description="Compelling story title")
    logline: str = Field(..., description="One-sentence premise")
    synopsis: str | None = Field(None, description="3-5 sentence full synopsis. Optional - derived from logline if absent.") # optional — derive from chapters if empty
    themes: list[str] = Field(
        default_factory=list, description="Active theme tags. Optional - derived from component bundle if absent."
    ) # optional — populated from bundle tags if empty
    chapter_count: int | None = Field(None, description="Number of chapters in the plan. Optional - derived from bundle if absent.") # optional — computed from len(chapters) if 0
    chapters: list[ChapterPlan] = Field(..., description="List of chapter plans")
    story_bible: dict[str, Any] = Field(
        ...,
        description="Keys: characters, world_state, tone, pacing_notes",
    ) # optional — empty dict if omitted


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


# ---------------------------------------------------------------------------
# Scene Writer Schemas (Phase 6)
# ---------------------------------------------------------------------------

class SceneContext(BaseModel):
    """Input context passed to SceneWriterAgent for a single scene.

    Assembled by SceneService from StoryScene ORM data, ChapterPlan data,
    and the story_bible extracted from Story.story_bible.
    """

    scene_id: UUID
    chapter_number: int
    chapter_title: str
    scene_number: int
    beat: str
    goal: str
    conflict: str
    outcome: str
    setting_note: str
    word_count_target: int
    protagonist_name: str
    protagonist_description: str
    antagonist_name: str
    antagonist_description: str
    tone: str
    pacing_notes: str


class SceneOutput(BaseModel):
    """Output returned by SceneWriterAgent after writing a single scene."""

    scene_id: UUID
    prose: str
    actual_word_count: int
    target_word_count: int
