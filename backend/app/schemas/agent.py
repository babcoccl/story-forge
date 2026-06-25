"""Pydantic response schemas for agent observability endpoints (Phase 11)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AgentTokenBreakdown(BaseModel):
    """Token totals for a single agent_name."""

    agent_name: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None


class StoryCostResponse(BaseModel):
    """Aggregated token cost summary for a story."""

    story_id: UUID
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None
    breakdown: list[AgentTokenBreakdown]


class AgentRunLogItem(BaseModel):
    """Single agent run record for the observability log."""

    id: UUID
    agent_name: str
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    retry_count: int
    created_at: datetime


class AgentRunLogResponse(BaseModel):
    """Paginated agent run log for a story."""

    story_id: UUID
    total: int
    offset: int
    limit: int
    items: list[AgentRunLogItem]