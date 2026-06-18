"""Component-related database models.

Tables:
  - component_types: Top-level taxonomy of story components.
  - components: Core component library (story building blocks).
  - component_constraints: Compatibility rules between component tags.
"""

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.mixins import TimestampMixin


# ---------------------------------------------------------------------------
# ComponentType
# ---------------------------------------------------------------------------

class ComponentType(Base, TimestampMixin):
    """Stores the top-level taxonomy of story components.

    Examples: character, setting, activity, plot_beat, trait, clothing, theme.
    """

    __tablename__ = "component_types"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    components: Mapped[list["Component"]] = relationship(back_populates="component_type")


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

class Component(Base, TimestampMixin):
    """Core component library.

    Each row is one story building block with a rich prose description used
    in LLM prompts, tags for search, and compatibility tags for the
    constraint engine.
    """

    __tablename__ = "components"
    __table_args__ = (
        Index("ix_components_component_type_id", "component_type_id"),
        Index("ix_components_slug", "slug"),
        Index("ix_components_is_active", "is_active"),
        Index("ix_components_tags_gin", "tags", postgresql_using="gin"),
        Index(
            "ix_components_compatibility_tags_gin",
            "compatibility_tags",
            postgresql_using="gin",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    component_type_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("component_types.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_fragment: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default="{}"
    )
    compatibility_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default="{}"
    )
    rarity_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    component_type: Mapped["ComponentType"] = relationship(back_populates="components")
    story_links: Mapped[list["StoryComponentLink"]] = relationship(
        "StoryComponentLink", back_populates="component"
    )


# ---------------------------------------------------------------------------
# ComponentConstraint
# ---------------------------------------------------------------------------

# Relation semantics:
#   requires  – subject CANNOT be used unless an object-tagged component is present.
#   excludes  – subject and object-tagged components CANNOT appear together (hard).
#   prefers   – subject scores higher when object-tagged component is present (soft).
#   avoids    – subject scores lower when object-tagged component is present (soft).

RELATION_VALUES = ("requires", "excludes", "prefers", "avoids")


class ComponentConstraint(Base, TimestampMixin):
    """Compatibility rules between component tags.

    The constraint engine reads these rows before sampling to enforce or
    prefer certain combinations.
    """

    __tablename__ = "component_constraints"
    __table_args__ = (
        UniqueConstraint("subject_tag", "relation", "object_tag", name="uq_constraints_subject_relation_object"),
        Index("ix_constraints_subject_tag", "subject_tag"),
        Index("ix_constraints_object_tag", "object_tag"),
        Index("ix_constraints_relation", "relation"),
        CheckConstraint(
            f"relation IN ({', '.join(repr(r) for r in RELATION_VALUES)})",
            name="ck_constraints_relation_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    subject_tag: Mapped[str] = mapped_column(String(200), nullable=False)
    relation: Mapped[str] = mapped_column(String(50), nullable=False)
    object_tag: Mapped[str] = mapped_column(String(200), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Forward reference import (StoryComponentLink defined in story.py)
# ---------------------------------------------------------------------------
from backend.app.models.story import StoryComponentLink  # noqa: F401,E402  # needed for relationship
