"""Agent run tracking models.

Tables:
  - agent_runs: Logs every agent invocation for observability and debugging.
"""

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.mixins import TimestampMixin


# ---------------------------------------------------------------------------
# AgentRun
# ---------------------------------------------------------------------------

class AgentRun(Base, TimestampMixin):
    """Logs every agent invocation for observability and debugging.

    Tracks input/output payloads, token usage, latency, retry counts,
    and error messages for each agent call.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_story_id", "story_id"),
        Index("ix_agent_runs_agent_name", "agent_name"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_scene_id", "scene_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    story_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id"), nullable=True
    )
    scene_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_scenes.id"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="'planner', 'scene_writer', 'continuity', 'judge', 'wordsmith', 'sampler'",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="'running', 'complete', 'failed', 'retried'",
    )
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    story: Mapped["Story | None"] = relationship(back_populates="agent_runs")
    scene: Mapped["StoryScene | None"] = relationship(back_populates="agent_runs")


# ---------------------------------------------------------------------------
# Forward references for type hints
# ---------------------------------------------------------------------------
from backend.app.models.story import Story, StoryScene  # noqa: E402,F401
