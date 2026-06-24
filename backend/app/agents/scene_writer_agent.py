"""SceneWriterAgent — writes prose for a single scene.

Receives a SceneContext containing the scene beat, story bible excerpt,
and word count target. Returns raw prose as a string via SceneOutput.

See SPEC_PHASE_6.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base_agent import AgentError, BaseAgent
from backend.app.schemas.story import SceneContext, SceneOutput

logger = logging.getLogger(__name__)


class SceneWriterAgent(BaseAgent):
    """Prose writer agent for individual story scenes.

    Calls the LLM once per scene using self.call() (not call_json —
    output is prose, not JSON). Retries up to 3 times on AgentError.
    Word count is validated post-generation but never blocks completion.
    """

    agent_name = "scene_writer"

    SYSTEM_PROMPT = (
        "You are a skilled fiction writer for a long-form story generation system. "
        "You write vivid, immersive scenes in third-person limited perspective. "
        "Each scene must hit its target word count within plus or minus ten percent. "
        "Do not summarize — write prose. Show, don't tell. "
        "Maintain character voice and tone from the story bible provided. "
        "End every scene with a clear narrative beat transition that sets up the next scene. "
        "Output prose only — no headers, no scene labels, no commentary. "
        "When a Continuity State section is provided, treat it as ground truth "
        "for current character locations, emotional states, and open narrative "
        "threads — your scene must be consistent with it."
    )

    @property
    def system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    async def write(
        self,
        db: AsyncSession,
        context: SceneContext,
        story_id: UUID,
    ) -> SceneOutput:
        """Write prose for one scene and return a SceneOutput.

        Parameters
        ----------
        db : AsyncSession
            Database session for AgentRun logging.
        context : SceneContext
            Full scene context assembled by SceneService.
        story_id : UUID
            Story record ID for AgentRun logging.

        Returns
        -------
        SceneOutput
            Prose string with actual and target word counts.

        Raises
        ------
        AgentError
            If all 3 attempts fail.
        """
        base_user_message = self._build_user_message(context)
        max_tokens = min(self._settings.llm_max_tokens, 32192)

        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            # On retries, append explicit directive to break identical-prompt loop.
            user_message = base_user_message
            if attempt > 1:
                user_message = (
                    base_user_message
                    + "\n\n[RETRY DIRECTIVE — attempt "
                    + str(attempt)
                    + " of "
                    + str(max_attempts)
                    + ": the previous attempt produced no output. "
                    "You must write the full scene prose now. "
                    "Do not output a thinking block. Output prose only.]"
                )
            try:
                prose = await self.call(
                    db=db,
                    story_id=story_id,
                    scene_id=context.scene_id,
                    user_message=user_message,
                    max_tokens=max_tokens,
                    response_format={"type": "text"},
                )
                # Empty prose from LLM is a retryable failure — raise AgentError
                # so the outer retry loop (attempt 1→2→3) handles it properly.
                if not prose.strip():
                    raise AgentError(
                        f"SceneWriterAgent received empty prose from LLM "
                        f"(scene={context.scene_id}, attempt={attempt})"
                    )
                logger.debug(
                    "SceneWriterAgent raw prose length: %d chars (scene=%s)",
                    len(prose),
                    context.scene_id,
                )
                actual_word_count = len(prose.split())
                deviation = abs(actual_word_count - context.word_count_target) / max(
                    context.word_count_target, 1
                )
                if deviation > 0.20:
                    logger.warning(
                        "Scene %s word count deviation %.0f%% "
                        "(actual=%d target=%d) — accepting prose as-is",
                        context.scene_id,
                        deviation * 100,
                        actual_word_count,
                        context.word_count_target,
                    )
                logger.info(
                    "SceneWriterAgent.write succeeded on attempt %d "
                    "(scene=%s words=%d)",
                    attempt,
                    context.scene_id,
                    actual_word_count,
                )
                return SceneOutput(
                    scene_id=context.scene_id,
                    prose=prose,
                    actual_word_count=actual_word_count,
                    target_word_count=context.word_count_target,
                )
            except AgentError as exc:
                last_error = exc
                logger.warning(
                    "SceneWriterAgent.write attempt %d failed (scene=%s): %s",
                    attempt,
                    context.scene_id,
                    exc,
                )

        raise AgentError(
            f"SceneWriterAgent failed after {max_attempts} attempts "
            f"(scene={context.scene_id}): {last_error}"
        )

    @staticmethod
    def _build_user_message(context: SceneContext) -> str:
        """Build the user message for a single scene."""
        lines = [
            "Story Bible:",
            f"  Protagonist  : {context.protagonist_name} — {context.protagonist_description}",
            f"  Antagonist   : {context.antagonist_name} — {context.antagonist_description}",
            f"  Tone         : {context.tone}",
            f"  Pacing notes : {context.pacing_notes}",
            "",
            f"Chapter {context.chapter_number}: {context.chapter_title}",
            f"Scene {context.scene_number}:",
            f"  Goal     : {context.goal}",
            f"  Conflict : {context.conflict}",
            f"  Outcome  : {context.outcome}",
            f"  Setting  : {context.setting_note}",
            f"  Target   : {context.word_count_target} words",
        ]

        if context.continuity_digest:
            lines.append("")
            lines.append("Continuity State (what has actually happened so far):")
            lines.append(context.continuity_digest)

        lines.append("")
        lines.append("Write the scene now. Output prose only — no headers, no commentary.")
        return "\n".join(lines)
