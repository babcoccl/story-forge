"""Story-related database models.

Tables:
  - stories: Top-level story record.
  - story_component_links: Junction table for components used in a story.
  - story_chapters: One row per chapter in a story.
  - story_scenes: One row per scene within a chapter.
"""

from sqlalchemy import (
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
# Story
# ---------------------------------------------------------------------------

class Story(Base, TimestampMixin):
    """The top-level story record.

    A story can be standalone or a continuation of a parent story.
    """

    __tablename__ = "stories"
    __table_args__ = (
        Index("ix_stories_status", "status"),
        Index("ix_stories_mode", "mode"),
        Index("ix_stories_parent_story_id", "parent_story_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="'standalone' or 'continuation'"
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="'pending', 'planning', 'writing', 'reviewing', 'complete', 'failed'",
    )
    generation_seed: Mapped[str | None] = mapped_column(String(200), nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=15000)
    actual_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_story_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stories.id"),
        nullable=True,
    )
    story_bible: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    style_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(
        "completed_at",
        nullable=True,
        comment="Stored as ISO string or timestamp",
    )

    # Relationships
    parent_story: Mapped["Story | None"] = relationship(
        "Story", remote_side="Story.id", backref="continuations"
    )
    chapters: Mapped[list["StoryChapter"]] = relationship(back_populates="story")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="story")


# ---------------------------------------------------------------------------
# StoryComponentLink
# ---------------------------------------------------------------------------

class StoryComponentLink(Base, TimestampMixin):
    """Junction table recording which components were used in a story.

    Tracks the role each component plays (protagonist, setting, etc.).
    """

    __tablename__ = "story_component_links"
    __table_args__ = (
        UniqueConstraint("story_id", "component_id", "role", name="uq_links_story_component_role"),
        Index("ix_links_story_id", "story_id"),
        Index("ix_links_component_id", "component_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    story_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False
    )
    component_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("components.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="e.g. protagonist, antagonist, primary_setting, main_activity",
    )

    # Relationships
    story: Mapped["Story"] = relationship(back_populates="component_links")
    component: Mapped["Component"] = relationship(
        "Component", back_populates="story_links"
    )


# ---------------------------------------------------------------------------
# StoryChapter
# ---------------------------------------------------------------------------

class StoryChapter(Base, TimestampMixin):
    """One row per chapter in a story."""

    __tablename__ = "story_chapters"
    __table_args__ = (
        UniqueConstraint("story_id", "chapter_number", name="uq_chapters_story_number"),
        Index("ix_chapters_story_id", "story_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    story_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="'pending', 'writing', 'reviewing', 'complete', 'failed'",
    )
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canon_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    story: Mapped["Story"] = relationship(back_populates="chapters")
    scenes: Mapped[list["StoryScene"]] = relationship(back_populates="chapter")


# ---------------------------------------------------------------------------
# StoryScene
# ---------------------------------------------------------------------------

class StoryScene(Base, TimestampMixin):
    """One row per scene within a chapter."""

    __tablename__ = "story_scenes"
    __table_args__ = (
        UniqueConstraint("chapter_id", "scene_number", name="uq_scenes_chapter_number"),
        Index("ix_scenes_chapter_id", "chapter_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    chapter_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_chapters.id"), nullable=False
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    beat: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="'pending', 'writing', 'complete', 'failed'",
    )
    continuity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    wordsmith_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    chapter: Mapped["StoryChapter"] = relationship(back_populates="scenes")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="scene")


# ---------------------------------------------------------------------------
# Forward references for type hints
# ---------------------------------------------------------------------------
from backend.app.models.component import Component  # noqa: E402,F401
from backend.app.models.agent import AgentRun  # noqa: E402,F401
