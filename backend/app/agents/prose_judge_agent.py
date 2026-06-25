"""ProseJudgeAgent — evaluates scene prose quality and returns structured verdict.

This agent scores scene prose on narrative immersion, prose quality,
character voice consistency, and scene pacing. It returns a structured
ProseJudgeVerdict with a numeric score, approval flag, and actionable
improvement notes.

This is distinct from JudgeAgent (backend/app/agents/judge_agent.py) which
evaluates component bundles for the sampler pipeline.

See SPEC_PHASE_12.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base_agent import BaseAgent
from backend.app.schemas.revision import ProseJudgeVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a prose quality evaluator for long-form fiction.

Your job is to evaluate a scene's prose on four criteria:
1. Narrative immersion — does the prose draw the reader in with sensory detail and emotional engagement?
2. Prose quality and sentence variety — is there rhythm, varied sentence structure, and precise word choice?
3. Character voice consistency — do characters sound distinct and in-character?
4. Scene pacing — does the scene move forward with purpose, balancing action, dialogue, and description?

Respond with a JSON object matching this exact schema:
{
  "score": <float 0.0-1.0>,
  "approved": <bool>,
  "improvement_notes": ["<note>", ...],
  "reasoning": "<one sentence>"
}

Rules:
- approved must be true if and only if score >= the threshold provided in the user message.
- improvement_notes should be empty if approved. Otherwise include 1-4 specific, actionable notes (e.g. "Vary sentence length in paragraphs 2-4" not "Improve prose").
- reasoning is a one-sentence summary of the verdict.
- Be strict but fair. Good prose earns 0.8+. Mediocre prose is 0.5-0.7. Truly poor prose is below 0.5.
""" + "/no_think"


class ProseJudgeAgent(BaseAgent):
    """Agent that scores scene prose and returns structured improvement feedback.

    Usage:
        async with ProseJudgeAgent() as agent:
            verdict = await agent.judge(db, prose, scene_id, story_id, threshold)
    """

    agent_name = "prose_judge"

    def __init__(self) -> None:
        super().__init__(_SYSTEM_PROMPT)

    async def judge(
        self,
        db: AsyncSession,
        scene_prose: str,
        scene_id: UUID,
        story_id: UUID,
        threshold: float,
    ) -> ProseJudgeVerdict:
        """Evaluate scene prose and return a structured verdict.

        Parameters
        ----------
        db : AsyncSession
            Active database session for logging the agent run.
        scene_prose : str
            The full prose text of the scene to evaluate.
        scene_id : UUID
            The story scene record ID (for agent run logging).
        story_id : UUID
            The parent story record ID.
        threshold : float
            Minimum acceptable score; verdict.approved is True when score >= threshold.

        Returns
        -------
        ProseJudgeVerdict
            Structured verdict with score, approval flag, notes, and reasoning.

        Raises
        ------
        AgentError
            If the LLM call fails.
        """
        user_message = (
            f"Threshold for approval: {threshold}\n\n"
            f"Evaluate the following scene prose:\n\n"
            f"{scene_prose}"
        )

        result = await self.call_json(
            db=db,
            user_message=user_message,
            scene_id=scene_id,
            story_id=story_id,
        )

        verdict = ProseJudgeVerdict(**result)

        # Enforce approved flag based on threshold regardless of model output
        verdict.approved = verdict.score >= threshold

        logger.info(
            "ProseJudgeAgent scored scene %s: score=%.2f approved=%s notes=%d",
            scene_id,
            verdict.score,
            verdict.approved,
            len(verdict.improvement_notes),
        )

        return verdict