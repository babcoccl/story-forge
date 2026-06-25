"""Pydantic schemas for the prose revision loop (Phase 12)."""

from pydantic import BaseModel, Field


class ProseJudgeVerdict(BaseModel):
    """Structured verdict returned by ProseJudgeAgent.

    Attributes:
        score: Quality score between 0.0 and 1.0.
        approved: True if score >= threshold (enforced by service layer).
        improvement_notes: 1-4 specific, actionable rewriting notes.
        reasoning: One-sentence summary of the verdict.
    """

    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Quality score from 0.0 (poor) to 1.0 (excellent).",
    )
    approved: bool = Field(
        ...,
        description="True if score >= threshold; enforced by caller.",
    )
    improvement_notes: list[str] = Field(
        default_factory=list,
        description="Specific, actionable improvement notes for WordsmithAgent.",
    )
    reasoning: str = Field(
        ...,
        description="One-sentence summary of the verdict.",
    )