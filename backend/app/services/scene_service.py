"""SceneService — orchestrates per-scene prose generation.

Iterates all pending StoryScene records for a story in chapter and scene
order, calls SceneWriterAgent once per scene, and persists the result.

Scenes are committed individually after each write so the pipeline is
resumable if interrupted. A failed scene is marked status="failed" and
the loop continues — scene failures never abort the full pipeline.

See SPEC_PHASE_6.md for full specification.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.agents.base_agent import AgentError
from backend.app.agents.continuity_agent import ContinuityAgent
from backend.app.agents.scene_writer_agent import SceneWriterAgent
from backend.app.db.session import AsyncSessionLocal
from backend.app.models.story import Story, StoryChapter, StoryScene
from backend.app.schemas.story import SceneContext, SceneOutput, StoryPlan

logger = logging.getLogger(__name__)


class SceneService:
    """Orchestrates SceneWriterAgent across all scenes in a story plan."""

    def __init__(self) -> None:
        pass

    async def write_all_scenes(
        self,
        db: AsyncSession,
        story: Story,
        plan: StoryPlan,
    ) -> list[SceneOutput]:
        """Write prose for every pending scene in the story.

        Chapters are processed sequentially (each chapter's continuity digest
        seeds the next chapter's scenes). Within each chapter, all scenes are
        written concurrently via asyncio.gather() for reduced wall-clock time.

        The continuity agent fires once per chapter boundary (not after the
        final chapter), summarizing the whole chapter rather than each scene.

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        story : Story
            The Story ORM object (must have story_bible populated).
        plan : StoryPlan
            The StoryPlan produced by PlannerAgent in Phase 5.

        Returns
        -------
        list[SceneOutput]
            SceneOutput for every scene attempted, including partial failures.
            Failed scenes will have prose="" and actual_word_count=0.
        """
        outputs: list[SceneOutput] = []
        running_digest: str = ""
        last_written_prose: str = ""  # tracks last scene prose for previous_scene_closing
        story_bible = story.story_bible or {}

        # Parse story_bible for investigation_spine (graceful fallback)
        investigation_spine: str | None = None
        try:
            from backend.app.schemas.story import StoryBible
            bible = StoryBible.model_validate(story_bible)
            investigation_spine = bible.investigation_spine
        except Exception as exc:
            logger.warning(
                "StoryBible validation failed, falling back to dict access: %s", exc
            )
            investigation_spine = story_bible.get("investigation_spine")

        protagonist_name = ""
        protagonist_description = ""
        antagonist_name = ""
        antagonist_description = ""
        tone = story_bible.get("tone", "")
        pacing_notes = story_bible.get("pacing_notes", "")

        characters = story_bible.get("characters", {})
        if isinstance(characters, dict):
            protagonist_name = characters.get("protagonist_name", "")
            protagonist_description = characters.get("protagonist_description", "")
            antagonist_name = characters.get("antagonist_name", "")
            antagonist_description = characters.get("antagonist_description", "")
        elif isinstance(characters, list) and len(characters) > 0:
            for char in characters:
                role = char.get("role", "")
                if role == "protagonist":
                    protagonist_name = char.get("name", "")
                    protagonist_description = char.get("description", "")
                elif role == "antagonist":
                    antagonist_name = char.get("name", "")
                    antagonist_description = char.get("description", "")

        total_chapters = len(plan.chapters)

        async with SceneWriterAgent() as writer, ContinuityAgent() as continuity:
            for chapter_idx, chapter_plan in enumerate(plan.chapters):
                # Defensive fallback: if chapter_number was not provided by LLM, derive it
                effective_chapter_number = chapter_plan.chapter_number or (chapter_idx + 1)

                chapter_orm = await self._load_chapter(
                    db, story.id, effective_chapter_number
                )
                if chapter_orm is None:
                    logger.error(
                        "Chapter %d not found in DB for story %s — skipping",
                        effective_chapter_number,
                        story.id,
                    )
                    continue

                # Mark chapter as writing before first scene starts
                chapter_orm.status = "writing"
                await db.commit()

                # Load all scene ORM records for this chapter
                scene_orms: list[StoryScene] = []
                for scene_plan in chapter_plan.scenes:
                    scene_orm = await self._load_scene(
                        db, chapter_orm.id, scene_plan.scene_number
                    )
                    if scene_orm is None:
                        logger.error(
                            "Scene %d not found in DB for chapter %s — skipping",
                            scene_plan.scene_number,
                            chapter_orm.id,
                        )
                        continue
                    scene_orms.append(scene_orm)

                # Build SceneContext for each scene with previous_scene_closing.
                # Only the first scene of the chapter receives previous_scene_closing
                # (last 200 words from the prior chapter's final scene). Intra-chapter
                # scenes with scene_number > 1 get None since they run concurrently
                # and cannot read each other's output yet.
                contexts: list[SceneContext] = []
                for idx, scene_plan in enumerate(chapter_plan.scenes):
                    # Find matching scene_orm (same order as chapter_plan.scenes)
                    scene_orm = scene_orms[idx] if idx < len(scene_orms) else None
                    if scene_orm is None:
                        continue

                    # Determine previous_scene_closing
                    previous_closing: str | None = None
                    if scene_plan.scene_number == 1 and last_written_prose:
                        # First scene of a chapter (or story) — pass last 200 words
                        words = last_written_prose.split()
                        previous_closing = " ".join(words[-200:]) if words else None

                    context = SceneContext(
                        scene_id=scene_orm.id,
                        chapter_number=effective_chapter_number,
                        chapter_title=chapter_plan.title,
                        scene_number=scene_plan.scene_number,
                        beat=scene_orm.beat or "",
                        goal=scene_plan.goal,
                        conflict=scene_plan.conflict,
                        outcome=scene_plan.outcome,
                        setting_note=scene_plan.setting_note or "Primary setting",
                        word_count_target=scene_orm.word_count or scene_plan.word_count_target or 1250,
                        protagonist_name=protagonist_name,
                        protagonist_description=protagonist_description,
                        antagonist_name=antagonist_name,
                        antagonist_description=antagonist_description,
                        tone=tone,
                        pacing_notes=pacing_notes,
                        continuity_digest=running_digest if running_digest else None,
                        previous_scene_closing=previous_closing,
                        scene_objective=scene_plan.scene_objective,
                        investigation_spine=investigation_spine,
                    )
                    contexts.append(context)

                # Wake server before dispatching concurrent scene writes
                await writer.wake_server()

                tasks = [
                    self._write_single_scene(writer, ctx, story.id, scene_orms[i].id)
                    for i, ctx in enumerate(contexts)
                ]
                chapter_results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                chapter_outputs: list[SceneOutput] = []
                for result in chapter_results:
                    if isinstance(result, Exception):
                        # asyncio.gather captured an exception
                        logger.error("Scene write task failed: %s", result)
                        # Find which scene failed (cannot determine from gather order,
                        # but we need to track failed outputs)
                        outputs.append(
                            SceneOutput(
                                scene_id=UUID("00000000-0000-0000-0000-000000000000"),
                                prose="",
                                actual_word_count=0,
                                target_word_count=0,
                            )
                        )
                    else:
                        outputs.append(result)
                        chapter_outputs.append(result)
                        if result.prose:
                            last_written_prose = result.prose

                # Run continuity agent at chapter boundary (NOT after final chapter)
                is_last_chapter = (chapter_idx + 1) == total_chapters
                if not is_last_chapter and chapter_outputs:
                    chapter_prose = "\n\n".join(
                        out.prose for out in chapter_outputs if out.prose
                    )
                    if chapter_prose:
                        try:
                            # Wake server before continuity agent (post-idle gap)
                            await continuity.wake_server()
                            running_digest = await continuity.update_digest(
                                db=db,
                                story_id=story.id,
                                scene_id=None,
                                scene_prose=chapter_prose,
                                prior_digest=running_digest,
                            )
                            # Store continuity notes on the chapter record
                            chapter_orm.continuity_notes = running_digest
                            await db.commit()
                        except Exception as exc:
                            logger.error(
                                "Continuity digest update failed for chapter %d of story %s: %s",
                                effective_chapter_number,
                                story.id,
                                exc,
                            )

                # Mark chapter complete if at least one scene completed
                has_complete = any(
                    sc.status == "complete"
                    for sc in chapter_orm.scenes
                    if sc.status in ("complete", "failed", "writing")
                )
                if has_complete:
                    chapter_orm.status = "complete"
                    await db.commit()
                    logger.info(
                        "Chapter %d marked complete for story %s",
                        chapter_plan.chapter_number,
                        story.id,
                    )

        return outputs

    async def _write_single_scene(
        self,
        writer: SceneWriterAgent,
        context: SceneContext,
        story_id: UUID,
        scene_id: UUID,
    ) -> SceneOutput:
        """Write prose for a single scene using an isolated database session.

        Each coroutine opens its own AsyncSessionLocal() to avoid concurrent
        access to a shared session's transaction state machine, which corrupts
        when multiple coroutines call await session.commit() simultaneously.

        Parameters
        ----------
        writer : SceneWriterAgent
            The scene writer agent instance.
        context : SceneContext
            Full scene context.
        story_id : UUID
            Story record ID for AgentRun logging.
        scene_id : UUID
            The scene record ID to load and update.

        Returns
        -------
        SceneOutput
            The written scene output.

        Raises
        ------
        AgentError
            If the writer fails (caught by asyncio.gather in caller).
        """
        async with AsyncSessionLocal() as session:
            scene_orm = await session.get(StoryScene, scene_id)
            if scene_orm is None:
                raise AgentError(f"Scene {scene_id} not found")

            scene_orm.status = "writing"
            await session.commit()

            try:
                output = await writer.write(session, context, story_id)
            except AgentError:
                scene_orm = await session.get(StoryScene, scene_id)
                scene_orm.status = "failed"
                await session.commit()
                raise

            scene_orm = await session.get(StoryScene, scene_id)
            scene_orm.content = output.prose
            scene_orm.word_count = output.actual_word_count
            scene_orm.status = "complete"
            await session.commit()

            logger.info(
                "Scene %s written: %d words",
                scene_id,
                output.actual_word_count,
            )
            return output

    async def _load_chapter(
        self,
        db: AsyncSession,
        story_id: UUID,
        chapter_number: int,
    ) -> StoryChapter | None:
        result = await db.execute(
            select(StoryChapter)
            .where(
                StoryChapter.story_id == story_id,
                StoryChapter.chapter_number == chapter_number,
            )
            .options(selectinload(StoryChapter.scenes))
        )
        return result.scalar_one_or_none()

    async def _load_scene(
        self,
        db: AsyncSession,
        chapter_id: UUID,
        scene_number: int,
    ) -> StoryScene | None:
        result = await db.execute(
            select(StoryScene).where(
                StoryScene.chapter_id == chapter_id,
                StoryScene.scene_number == scene_number,
            )
        )
        return result.scalar_one_or_none()