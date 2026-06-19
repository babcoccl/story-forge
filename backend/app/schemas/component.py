"""Pydantic schemas for component-related request/response validation.

Schemas:
  - ComponentTypeCreate, ComponentTypeRead, ComponentTypeUpdate
  - ComponentCreate, ComponentRead, ComponentUpdate
  - ConstraintCreate, ConstraintRead, ConstraintUpdate
  - BatchImportFile
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from backend.app.models.component import RELATION_VALUES


# ---------------------------------------------------------------------------
# ComponentType Schemas
# ---------------------------------------------------------------------------

class ComponentTypeCreate(BaseModel):
    """Used to insert a new component type."""

    name: str = Field(
        ...,
        max_length=100,
        pattern=r"^[a-z_]+$",
        description="Machine name for the component type (e.g. 'character', 'setting').",
    )
    display_name: str = Field(
        ...,
        max_length=200,
        description="Human-readable display name.",
    )
    description: str | None = None
    is_active: bool = True


class ComponentTypeRead(ComponentTypeCreate):
    """Returned when reading a component type."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class ComponentTypeUpdate(BaseModel):
    """All fields optional. Used for PATCH operations."""

    display_name: str | None = None
    description: str | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Component Schemas
# ---------------------------------------------------------------------------

class ComponentCreate(BaseModel):
    """Used to insert a new component."""

    component_type_id: UUID
    name: str = Field(..., max_length=200)
    slug: str = Field(..., max_length=200, pattern=r"^[a-z0-9\-]+$")
    description: str = Field(..., min_length=10)
    prompt_fragment: str | None = None
    tags: list[str] = []
    compatibility_tags: list[str] = []
    rarity_weight: float = Field(default=1.0, ge=0.01, le=100.0)
    metadata: dict | None = None
    is_active: bool = True


class ComponentRead(ComponentCreate):
    """Returned when reading a component."""

    id: UUID
    created_at: datetime
    updated_at: datetime
    component_type: "ComponentTypeRead | None" = None


class ComponentUpdate(BaseModel):
    """All fields optional. Used for PATCH operations."""

    name: str | None = None
    description: str | None = None
    prompt_fragment: str | None = None
    tags: list[str] | None = None
    compatibility_tags: list[str] | None = None
    rarity_weight: float | None = None
    metadata: dict | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Constraint Schemas
# ---------------------------------------------------------------------------

class ConstraintCreate(BaseModel):
    """Used to insert a constraint rule."""

    subject_tag: str = Field(..., max_length=200)
    relation: str = Field(
        ...,
        description='One of: "requires", "excludes", "prefers", "avoids".',
    )
    object_tag: str = Field(..., max_length=200)
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    description: str | None = None
    is_active: bool = True

    @field_validator("relation")
    @classmethod
    def validate_relation(cls, v: str) -> str:
        if v not in RELATION_VALUES:
            raise ValueError(
                f"relation must be one of {RELATION_VALUES}, got {v!r}"
            )
        return v


class ConstraintRead(ConstraintCreate):
    """Extends ConstraintCreate plus id, created_at, updated_at."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class ConstraintUpdate(BaseModel):
    """All fields optional."""

    strength: float | None = None
    description: str | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Batch Import Schema
# ---------------------------------------------------------------------------

class BatchImportComponent(BaseModel):
    """A component entry in the batch import file.

    Uses a `component_type` string key (type name) instead of `component_type_id`.
    """

    component_type: str
    name: str = Field(..., max_length=200)
    slug: str = Field(..., max_length=200, pattern=r"^[a-z0-9\-]+$")
    description: str = Field(..., min_length=10)
    prompt_fragment: str | None = None
    tags: list[str] = []
    compatibility_tags: list[str] = []
    rarity_weight: float = Field(default=1.0, ge=0.01, le=100.0)
    metadata: dict | None = None
    is_active: bool = True


class BatchImportFile(BaseModel):
    """Top-level schema for the seed JSON file."""

    component_types: list[ComponentTypeCreate] = []
    components: list[BatchImportComponent] = []
    constraints: list[ConstraintCreate] = []