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
        "End every scene on a concrete in-world action, image, or spoken line — never a summary sentence describing what will happen next. "
        "Do not write transition sentences, setup paragraphs, or any line that names what the protagonist 'is about to do' or 'must now face'. "
        "Write only this scene's content. "
        "Output prose only — no headers, no scene labels, no commentary. "
        "When a Continuity State section is provided, treat it as ground truth "
        "for current character locations, emotional states, and open narrative "
        "threads — your scene must be consistent with it. "
        "When ARTIFACT LOCKS are provided, you must refer to each artifact by its exact canonical name — "
        "never by a synonym, pronoun only, or alternative description. "
        "When CHARACTER ROLE LOCKS are provided, each character's role is frozen — "
        "a contact cannot become a captive, a dealer cannot become an ally."
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
        base_user_message = self._build_user_message(context)
        max_tokens = max(int(context.word_count_target * 1.15 / 0.75), 2048)

        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            user_message = base_user_message
            if attempt > 1:
                user_message = (
                    base_user_message
                    + f"\n\n[RETRY DIRECTIVE — attempt {attempt} of {max_attempts}: "
                    "the previous attempt produced no output. "
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
                if not prose.strip():
                    raise AgentError(
                        f"SceneWriterAgent received empty prose from LLM "
                        f"(scene={context.scene_id}, attempt={attempt})"
                    )

                # --- Continue pass: if under 85% of target, request continuation ---
                prose = await self._continue_if_short(
                    db, prose, context, story_id, max_tokens
                )
                # -------------------------------------------------------------------

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
            f"  Target   : {context.word_count_target} words "
            f"(write between {int(context.word_count_target * 0.85)} "
            f"and {int(context.word_count_target * 1.15)} words)",
        ]

        if context.investigation_spine:
            lines.append(f"  Story spine  : {context.investigation_spine}")

        if context.scene_objective:
            lines.append(f"  Objective    : {context.scene_objective}")

        # Inject artifact canonical lock
        if context.artifacts:
            lines.append("")
            lines.append("ARTIFACT LOCKS (canonical — never rename or re-describe these):")
            for artifact in context.artifacts:
                lines.append(
                    f"  [{artifact.canonical_name}]: {artifact.description}"
                    + (f" — current state: {artifact.current_state}" if artifact.current_state else "")
                )

        # Inject character role lock table
        if context.characters:
            lines.append("")
            lines.append("CHARACTER ROLE LOCKS (these roles do not change):")
            for name, role in context.characters.items():
                lines.append(f"  {name}: {role}")

        if context.continuity_digest:
            lines.append("")
            lines.append("Continuity State (what has actually happened so far):")
            lines.append(context.continuity_digest)

        if context.previous_scene_closing:
            lines.append("")
            lines.append("Closing lines of the previous scene (maintain narrative flow):")
            lines.append(context.previous_scene_closing)

        lines.append("")
        lines.append(
            "Write the scene now. End on the last action or image of the scene — "
            "a moment, a line of dialogue, or a physical detail. "
            "Do not write a closing summary or transition sentence. "
            "Output prose only — no headers, no commentary."
        )
        return "\n".join(lines)
    
    async def _continue_if_short(
    self,
    db: AsyncSession,
    prose: str,
    context: SceneContext,
    story_id: UUID,
    max_tokens: int,
    ) -> str:
        """If prose is under 85% of target, request a continuation pass.

        Sends the existing prose back as context with an explicit instruction
        to continue writing from the last sentence until the word count target
        is reached. Runs at most once — if the continuation is also short,
        we accept it rather than looping indefinitely.
        """
        current_words = len(prose.split())
        floor = int(context.word_count_target * 0.85)

        if current_words >= floor:
            return prose  # already within range, nothing to do

        remaining_words = context.word_count_target - current_words
        remaining_tokens = max(int(remaining_words / 0.75), 512)

        logger.info(
            "Scene %s under target (%d/%d words) — requesting continuation (%d more words)",
            context.scene_id,
            current_words,
            context.word_count_target,
            remaining_words,
        )

        # Build a continuation prompt: original context + what was written + directive
        continuation_message = (
            self._build_user_message(context)
            + "\n\n--- SCENE SO FAR (do not repeat this) ---\n"
            + prose
            + "\n--- END OF SCENE SO FAR ---\n\n"
            + f"The scene above is {current_words} words. "
            + "Continue writing from the last sentence above. "
            + f"Write approximately {remaining_words} more words to reach the {context.word_count_target}-word target. "
            + "Do not repeat or summarize what was already written. "
            + "Continue the prose seamlessly from where it left off. "
            + "Output only the new continuation prose."
        )

        try:
            continuation = await self.call(
                db=db,
                story_id=story_id,
                scene_id=context.scene_id,
                user_message=continuation_message,
                max_tokens=remaining_tokens,
                response_format={"type": "text"},
            )
            if continuation.strip():
                combined = prose.rstrip() + "\n\n" + continuation.strip()
                logger.info(
                    "Continuation pass added %d words to scene %s (total now %d)",
                    len(continuation.split()),
                    context.scene_id,
                    len(combined.split()),
                )
                return combined
        except AgentError as exc:
            logger.warning(
                "Continuation pass failed for scene %s — keeping original prose: %s",
                context.scene_id,
                exc,
            )

        return prose  # continuation failed — return what we have
