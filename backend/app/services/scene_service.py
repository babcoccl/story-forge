"""SceneService — orchestrates per-scene prose generation.

Iterates all pending StoryScene records for a story in chapter and scene
order, calls SceneWriterAgent once per scene, and persists the result.

Scenes are committed individually after each write so the pipeline is
resumable if interrupted. A failed scene is marked status="failed" and
the loop continues — scene failures never abort the full pipeline.

See SPEC_PHASE_6.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.agents.base_agent import AgentError
from backend.app.agents.continuity_agent import ContinuityAgent
from backend.app.agents.scene_writer_agent import SceneWriterAgent
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

        Iterates plan.chapters in order, then each chapter's scenes in order.
        For each scene, loads the StoryScene ORM record, builds a SceneContext,
        calls SceneWriterAgent.write(), persists the result, and commits.

        Failed scenes are marked status="failed" and logged. The loop always
        continues regardless of individual scene failures.

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
        story_bible = story.story_bible or {}

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
            # Handle list-of-dict format if LLM produced that structure
            for char in characters:
                role = char.get("role", "")
                if role == "protagonist":
                    protagonist_name = char.get("name", "")
                    protagonist_description = char.get("description", "")
                elif role == "antagonist":
                    antagonist_name = char.get("name", "")
                    antagonist_description = char.get("description", "")

        async with SceneWriterAgent() as writer, ContinuityAgent() as continuity:
            for chapter_plan in plan.chapters:
                chapter_orm = await self._load_chapter(
                    db, story.id, chapter_plan.chapter_number
                )
                if chapter_orm is None:
                    logger.error(
                        "Chapter %d not found in DB for story %s — skipping",
                        chapter_plan.chapter_number,
                        story.id,
                    )
                    continue

                # Mark chapter as writing before first scene starts
                chapter_orm.status = "writing"
                await db.commit()

                # Pre-compute max scene number for last-scene detection
                max_scene_number = max(sp.scene_number for sp in chapter_plan.scenes)

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

                    context = SceneContext(
                        scene_id=scene_orm.id,
                        chapter_number=chapter_plan.chapter_number,
                        chapter_title=chapter_plan.title,
                        scene_number=scene_plan.scene_number,
                        beat=scene_orm.beat or "",
                        goal=scene_plan.goal,
                        conflict=scene_plan.conflict,
                        outcome=scene_plan.outcome,
                        setting_note=scene_plan.setting_note or "Primary setting",
                        word_count_target=scene_plan.word_count_target or 1250,
                        protagonist_name=protagonist_name,
                        protagonist_description=protagonist_description,
                        antagonist_name=antagonist_name,
                        antagonist_description=antagonist_description,
                        tone=tone,
                        pacing_notes=pacing_notes,
                        continuity_digest=running_digest if running_digest else None,
                    )

                    try:
                        scene_orm.status = "writing"
                        await db.commit()

                        output = await writer.write(db, context, story.id)
                        scene_orm.content = output.prose
                        scene_orm.word_count = output.actual_word_count
                        scene_orm.status = "complete"
                        await db.commit()

                        # Update continuity digest after successful scene write
                        try:
                            running_digest = await continuity.update_digest(
                                db=db,
                                story_id=story.id,
                                scene_id=scene_orm.id,
                                scene_prose=output.prose,
                                prior_digest=running_digest,
                            )
                            scene_orm.continuity_notes = running_digest
                            await db.commit()
                            logger.debug(
                                "Continuity digest updated after scene %s (%d chars)",
                                scene_orm.id,
                                len(running_digest),
                            )
                        except Exception as exc:
                            logger.warning(
                                "ContinuityAgent failed for scene %s — skipping: %s",
                                scene_orm.id,
                                exc,
                            )

                        logger.info(
                            "Scene %s written: %d words",
                            scene_orm.id,
                            output.actual_word_count,
                        )
                        outputs.append(output)

                    except AgentError as exc:
                        logger.error(
                            "SceneWriterAgent failed for scene %s: %s",
                            scene_orm.id,
                            exc,
                        )
                        scene_orm.status = "failed"
                        await db.commit()
                        outputs.append(
                            SceneOutput(
                                scene_id=scene_orm.id,
                                prose="",
                                actual_word_count=0,
                                target_word_count=context.word_count_target,
                            )
                        )

                    # After last scene in chapter, mark chapter complete if
                    # at least one scene completed successfully
                    if scene_plan.scene_number == max_scene_number:
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