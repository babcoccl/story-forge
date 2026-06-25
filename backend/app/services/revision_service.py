"""RevisionService — orchestrates the ProseJudge × Wordsmith revision loop.

After all scenes are written by SceneWriterAgent, this service runs a prose
quality pass on every successfully completed scene:

1. ProseJudgeAgent scores each scene on quality criteria.
2. If below threshold, WordsmithAgent rewrites using judge's improvement notes.
3. A second judge pass determines whether to accept the rewrite.
4. Each scene is attempted at most `max_revisions` times (default 2).

See SPEC_PHASE_12.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.app.agents.base_agent import AgentError
from backend.app.agents.prose_judge_agent import ProseJudgeAgent
from backend.app.agents.wordsmith_agent import WordsmithAgent
from backend.app.models.story import Story, StoryChapter, StoryScene

logger = logging.getLogger(__name__)


class RevisionService:
    """Service layer for the judge-rewrite prose quality revision loop."""

    def __init__(self) -> None:
        """Initialize RevisionService.

        Agents are instantiated inside `run_revision_loop` as context managers.
        """

    async def run_revision_loop(
        self,
        db: AsyncSession,
        story: Story,
        threshold: float,
        max_revisions: int,
    ) -> None:
        """Run the prose quality revision loop for all complete scenes.

        Loads all `StoryScene` records with `status == "complete"` and
        `content` not None, ordered by chapter number then scene number.
        Opens both ProseJudgeAgent and WordsmithAgent as context managers.
        For each scene, judges, rewrites (if needed), and re-judges.

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        story : Story
            The story record whose scenes will be reviewed.
        threshold : float
            Minimum acceptable prose quality score (0.0–1.0).
        max_revisions : int
            Maximum revision attempts per scene (capped at 2).

        Returns
        -------
        None
            Changes are persisted to the database directly.
        """
        # Step 1: Load all complete scenes ordered by chapter then scene number
        stmt = (
            select(StoryScene)
            .join(StoryScene.chapter)
            .where(
                StoryChapter.story_id == story.id,
                StoryScene.status == "complete",
                StoryScene.content.isnot(None),
            )
            .options(joinedload(StoryScene.chapter))
            .order_by(StoryChapter.chapter_number, StoryScene.scene_number)
        )
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        logger.info(
            "Revision loop: loaded %d complete scenes for story %s",
            len(scenes),
            story.id,
        )

        # Step 2: Open both agents as nested context managers
        async with (
            ProseJudgeAgent() as judge,
            WordsmithAgent() as wordsmith,
        ):
            # Step 3: Process each scene
            for scene in scenes:
                await self._process_scene(
                    db=db,
                    scene=scene,
                    story_id=story.id,
                    judge=judge,
                    wordsmith=wordsmith,
                    threshold=threshold,
                    max_revisions=max_revisions,
                )

    async def _process_scene(
        self,
        db: AsyncSession,
        scene: StoryScene,
        story_id: UUID,
        judge: ProseJudgeAgent,
        wordsmith: WordsmithAgent,
        threshold: float,
        max_revisions: int,
    ) -> None:
        """Process a single scene through the judge-rewrite loop.

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        scene : StoryScene
            The scene record to evaluate and potentially rewrite.
        story_id : UUID
            The story record ID.
        judge : ProseJudgeAgent
            The prose judge agent instance.
        wordsmith : WordsmithAgent
            The wordsmith agent instance.
        threshold : float
            Minimum acceptable score.
        max_revisions : int
            Maximum revision attempts per scene.
        """
        # 3a: Judge the scene
        try:
            verdict = await judge.judge(
                db=db,
                scene_prose=scene.content,
                scene_id=scene.id,
                story_id=story_id,
                threshold=threshold,
            )
        except AgentError as exc:
            logger.warning(
                "Judge failed for scene %s — skipping: %s",
                scene.id,
                exc,
            )
            return

        # 3b: If approved, skip rewrite
        if verdict.approved:
            logger.debug(
                "Scene %s approved with score %.2f — no rewrite needed",
                scene.id,
                verdict.score,
            )
            return

        # 3c: If at revision cap, skip rewrite
        if scene.revision_count >= max_revisions:
            logger.warning(
                "Scene %s exceeded revision cap (%d) — keeping original prose",
                scene.id,
                max_revisions,
            )
            return

        # 3d: Not approved, under cap — attempt rewrite
        original_score = verdict.score
        original_prose = scene.content

        try:
            rewritten_prose = await wordsmith.rewrite(
                db=db,
                original_prose=original_prose,
                improvement_notes=verdict.improvement_notes,
                continuity_notes=scene.continuity_notes,
                scene_id=scene.id,
                story_id=story_id,
                word_count_target=scene.word_count or 0,
            )
        except AgentError as exc:
            logger.warning(
                "Wordsmith rewrite failed for scene %s — keeping original: %s",
                scene.id,
                exc,
            )
            return

        # Run second judge pass on rewritten prose
        try:
            second_verdict = await judge.judge(
                db=db,
                scene_prose=rewritten_prose,
                scene_id=scene.id,
                story_id=story_id,
                threshold=threshold,
            )
        except AgentError as exc:
            logger.warning(
                "Second judge pass failed for scene %s — keeping original: %s",
                scene.id,
                exc,
            )
            return

        # Compare scores: accept rewrite only if it improved or stayed neutral
        if second_verdict.score >= original_score:
            # Apply the rewrite
            scene.content = rewritten_prose
            scene.word_count = len(rewritten_prose.split())
            scene.revision_count += 1
            scene.wordsmith_notes = "; ".join(verdict.improvement_notes)
            await db.commit()
            logger.info(
                "Scene %s rewrite accepted: score %.2f → %.2f, revision_count=%d",
                scene.id,
                original_score,
                second_verdict.score,
                scene.revision_count,
            )
        else:
            # Rewrite made it worse — keep original
            logger.warning(
                "Scene %s rewrite made prose worse: %.2f → %.2f — keeping original",
                scene.id,
                original_score,
                second_verdict.score,
            )