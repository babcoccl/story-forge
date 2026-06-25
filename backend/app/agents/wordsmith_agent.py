"""WordsmithAgent — rewrites scene prose addressing judge improvement notes.

This agent receives original scene prose, specific improvement notes from
ProseJudgeAgent, and optional continuity context. It rewrites the scene
addressing every improvement note while preserving all plot events, character
positions, and narrative outcomes from the original.

See SPEC_PHASE_12.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base_agent import AgentError, BaseAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a prose rewriter for long-form fiction.

You will receive:
1. Original scene prose
2. Specific improvement notes from a quality reviewer
3. Optional continuity context (treat as ground truth)
4. A target word count

Your job is to rewrite the scene addressing EVERY improvement note while:
- Preserving all plot events, character positions, and narrative outcomes
- Maintaining approximately the same word count (within ±15% of target)
- Keeping the same point of view and tense as the original
- Outputting prose only — no headers, no commentary, no meta-notes

Do not add or remove scenes. Do not change the story outcome. Focus purely on
prose quality improvements as specified by the reviewer's notes.
""" + "/no_think"


class WordsmithAgent(BaseAgent):
    """Agent that rewrites scene prose based on judge improvement feedback.

    Usage:
        async with WordsmithAgent() as agent:
            rewritten = await agent.rewrite(
                db, original, notes, continuity, scene_id, story_id, target
            )
    """

    agent_name = "wordsmith"

    def __init__(self) -> None:
        super().__init__(_SYSTEM_PROMPT)

    async def rewrite(
        self,
        db: AsyncSession,
        original_prose: str,
        improvement_notes: list[str],
        continuity_notes: str | None,
        scene_id: UUID,
        story_id: UUID,
        word_count_target: int,
    ) -> str:
        """Rewrite scene prose addressing the judge's improvement notes.

        Parameters
        ----------
        db : AsyncSession
            Active database session for logging the agent run.
        original_prose : str
            The original scene prose to rewrite.
        improvement_notes : list[str]
            Specific, actionable improvement notes from ProseJudgeAgent.
        continuity_notes : str | None
            Optional continuity context to preserve as ground truth.
        scene_id : UUID
            The story scene record ID (for agent run logging).
        story_id : UUID
            The parent story record ID.
        word_count_target : int
            Target word count for the rewritten scene.

        Returns
        -------
        str
            The rewritten scene prose.

        Raises
        ------
        AgentError
            If the LLM call fails or returns empty prose.
        """
        notes_section = "Improvement notes from quality review:\n"
        for note in improvement_notes:
            notes_section += f"- {note}\n"

        user_message = (
            f"Original scene prose:\n\n{original_prose}\n\n"
            f"{notes_section}"
        )

        if continuity_notes:
            user_message += f"Continuity context (treat as ground truth):\n\n{continuity_notes}\n\n"

        user_message += (
            f"Target word count: {word_count_target} words\n\n"
            "Rewrite the scene now. Output prose only."
        )

        rewritten = await self.call(
            db=db,
            user_message=user_message,
            scene_id=scene_id,
            story_id=story_id,
        )

        if not rewritten.strip():
            raise AgentError("WordsmithAgent received empty prose from LLM")

        logger.info(
            "WordsmithAgent rewrote scene %s: original_chars=%d rewritten_chars=%d",
            scene_id,
            len(original_prose),
            len(rewritten),
        )

        return rewritten.strip()