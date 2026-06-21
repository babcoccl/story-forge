"""Story domain models.

Models for Story, StoryChapter, StoryScene, and StoryComponentLink.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from backend.app.models.agent import AgentRun
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.declarative_base import Base as DeclarativeBase
from backend.app.models.mixins import TimestampMixin


class Story(TimestampMixin, DeclarativeBase):
    """Root story record."""

    __tablename__ = "stories"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )
    parent_story_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="standalone | continuation"
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    story_bible: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Story bible JSON: tone, pacing_notes, characters, setting, world_building",
    )
    themes: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="List of theme strings",
    )
    target_word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_seed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="planning",
        comment="planning | writing | assembled | complete | failed",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logline: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Relationships
    chapters: Mapped[List["StoryChapter"]] = relationship(
        "StoryChapter", back_populates="story", cascade="all, delete-orphan"
    )
    component_links: Mapped[List["StoryComponentLink"]] = relationship(
        "StoryComponentLink", back_populates="story", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[List["AgentRun"]] = relationship(
        "AgentRun", back_populates="story"
    )
    parent: Mapped["Story | None"] = relationship(
        "Story", remote_side=[id], backref="children"
    )


class StoryChapter(TimestampMixin, DeclarativeBase):
    """Chapter within a story."""

    __tablename__ = "story_chapters"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )
    story_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Assembled prose for this chapter, populated by ChapterService",
    )
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="pending",
        comment="pending | writing | complete | failed",
    )

    # Relationships
    story: Mapped["Story"] = relationship("Story", back_populates="chapters")
    scenes: Mapped[List["StoryScene"]] = relationship(
        "StoryScene", back_populates="chapter", cascade="all, delete-orphan"
    )


class StoryScene(TimestampMixin, DeclarativeBase):
    """Scene within a chapter."""

    __tablename__ = "story_scenes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )
    chapter_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("story_chapters.id", ondelete="CASCADE"),
        nullable=False,
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    beat: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="pending",
        comment="pending | writing | complete | failed",
    )

    # Relationships
    chapter: Mapped["StoryChapter"] = relationship("StoryChapter", back_populates="scenes")
    agent_runs: Mapped[List["AgentRun"]] = relationship(
        "AgentRun", back_populates="scene"
    )


class StoryComponentLink(DeclarativeBase):
    """Associates a story with a sampled component."""

    __tablename__ = "story_component_links"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )
    story_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        comment="ID of the sampled component from the components table",
    )
    role: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Role this component plays: protagonist, antagonist, setting, inciting_incident, etc.",
    )

    # Relationships
    story: Mapped["Story"] = relationship("Story", back_populates="component_links")