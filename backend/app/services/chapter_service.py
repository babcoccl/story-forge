"""ChapterService — assembles per-scene prose into chapter content.

After SceneService completes, ChapterService concatenates all completed
scene prose within each chapter, updates StoryChapter.content and
StoryChapter.word_count, then updates Story.actual_word_count and
Story.status = "assembled".

See SPEC_PHASE_6.md for full specification.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.story import Story, StoryChapter

logger = logging.getLogger(__name__)


class ChapterService:
    """Assembles completed scene prose into chapter and story content."""

    async def assemble_chapters(
        self,
        db: AsyncSession,
        story: Story,
    ) -> None:
        """Assemble all completed scenes into chapter content.

        For each StoryChapter in the story (ordered by chapter_number):
        - Load all StoryScene records where status="complete", ordered
          by scene_number.
        - Concatenate prose with double newline between scenes.
        - Set StoryChapter.content, StoryChapter.word_count,
          StoryChapter.status = "complete".
        - Commit after each chapter.

        After all chapters, set Story.actual_word_count and
        Story.status = "assembled". Commits once at the end.

        Chapters with zero completed scenes are set status="failed"
        and logged. Assembly never raises — partial results are accepted.

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        story : Story
            The Story ORM object with chapters to assemble.
        """
        chapters_stmt = (
            select(StoryChapter)
            .where(StoryChapter.story_id == story.id)
            .order_by(StoryChapter.chapter_number)
            .options(selectinload(StoryChapter.scenes))
        )
        result = await db.execute(chapters_stmt)
        chapters = result.scalars().all()

        total_word_count = 0

        for chapter in chapters:
            completed_scenes = sorted(
                [s for s in chapter.scenes if s.status == "complete"],
                key=lambda s: s.scene_number,
            )

            if not completed_scenes:
                logger.warning(
                    "Chapter %d (id=%s) has no completed scenes — marking failed",
                    chapter.chapter_number,
                    chapter.id,
                )
                chapter.status = "failed"
                await db.commit()
                continue

            assembled_prose = "\n\n".join(
                s.content for s in completed_scenes if s.content
            )
            chapter_word_count = len(assembled_prose.split())

            chapter.content = assembled_prose
            chapter.word_count = chapter_word_count
            chapter.status = "complete"
            await db.commit()

            total_word_count += chapter_word_count
            logger.info(
                "Chapter %d assembled: %d words from %d scenes",
                chapter.chapter_number,
                chapter_word_count,
                len(completed_scenes),
            )

        story.actual_word_count = total_word_count
        story.status = "assembled"
        await db.commit()
        logger.info(
            "Story %s assembled: %d total words across %d chapters",
            story.id,
            total_word_count,
            len(chapters),
        )