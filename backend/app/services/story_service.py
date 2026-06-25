"""StoryService — orchestrates story creation via Reroll + Planner + SceneWriter pipeline.

Responsible for:
1. Creating Story records
2. Calling RerollService to get approved component bundle
3. Linking components to the story
4. Calling PlannerAgent to generate structured plan
5. Creating StoryChapter and StoryScene records from the plan
6. Calling SceneWriterAgent to write prose for each scene
7. Assembling chapter content from scene prose
8. Updating Story with final word counts and status="assembled"

Phase 7 additions:
- reroll_story(): re-runs the full pipeline on an existing story record.

See SPEC_PHASE_6.md and SPEC_PHASE_7.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.agents.planner_agent import PlannerAgent
from backend.app.config import get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.models.story import Story, StoryChapter, StoryComponentLink, StoryScene
from backend.app.schemas.sampler import BundleItem, SampleRequest
from backend.app.schemas.story import RerollRequest, StoryCreateRequest, StoryPlan
from backend.app.services.chapter_service import ChapterService
from backend.app.services.reroll_service import RerollService
from backend.app.services.revision_service import RevisionService
from backend.app.services.scene_service import SceneService

logger = logging.getLogger(__name__)


class StoryService:
    """Service layer for story creation and management.

    Orchestrates the RerollService (component sampling + judge approval),
    PlannerAgent (structured story plan generation), SceneWriterAgent
    (per-scene prose generation), and ChapterService (chapter assembly)
    to produce a complete assembled story record.
    """

    def __init__(self) -> None:
        self._reroll = RerollService()
        self._planner = PlannerAgent()
        self._scene_service = SceneService()
        self._chapter_service = ChapterService()
        self._revision_service = RevisionService()

    # ------------------------------------------------------------------
    # Public API — fast path (returns immediately)
    # ------------------------------------------------------------------

    async def create_story_record(
        self,
        request: StoryCreateRequest,
    ) -> Story:
        """Create a Story record and return it immediately (pipeline runs later).

        Opens its own AsyncSessionLocal session, inserts and flushes the Story
        row (status="planning"), commits, and returns the ORM object with id
        populated.  Does NOT run the generation pipeline.

        Parameters
        ----------
        request : StoryCreateRequest
            Client request with mode, seed, overrides, target_word_count.

        Returns
        -------
        Story
            Persisted Story ORM object (id populated, status="planning").
        """
        db = AsyncSessionLocal()
        try:
            story = Story(
                mode=request.mode,
                target_word_count=request.target_word_count,
                status="planning",
            )

            if request.parent_story_id is not None:
                story.parent_story_id = request.parent_story_id

            db.add(story)
            await db.flush()
            await db.commit()
            return story
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

    # ------------------------------------------------------------------
    # Public API — slow path (background task)
    # ------------------------------------------------------------------

    async def run_pipeline(
        self,
        story_id: UUID,
        request: StoryCreateRequest,
    ) -> None:
        """Run the full generation pipeline for an existing story record.

        Opens its own AsyncSessionLocal session, loads the Story by *story_id*,
        runs the full pipeline, and persists the result.  Intended to be
        registered as a FastAPI BackgroundTask.

        Parameters
        ----------
        story_id : UUID
            The id of the pre-created Story record.
        request : StoryCreateRequest
            The original client request.

        Returns
        -------
        None
            Result is persisted to the database, not returned to the caller.
        """
        async with AsyncSessionLocal() as db:
            try:
                story = await self.get_story_by_id(db, story_id)
                if story is None:
                    logger.error("run_pipeline: story %s not found", story_id)
                    return

                await self._execute_pipeline(db, story, request)
            except Exception as exc:
                logger.error("Pipeline failed for story %s: %s", story_id, exc)
                story = await self.get_story_by_id(db, story_id)
                if story is not None:
                    await self._mark_failed(db, story, str(exc))
                raise

    # ------------------------------------------------------------------
    # Public API — legacy (direct call with caller-provided session)
    # ------------------------------------------------------------------

    async def create_story(
        self,
        db: AsyncSession,
        request: StoryCreateRequest,
    ) -> Story:
        """Create a new story and run the full pipeline synchronously.

        Kept for backward compatibility (e.g. CLI scripts, tests).
        For the HTTP API, prefer create_story_record() + run_pipeline().
        """
        story = Story(
            mode=request.mode,
            target_word_count=request.target_word_count,
            status="planning",
        )

        if request.parent_story_id is not None:
            story.parent_story_id = request.parent_story_id

        db.add(story)
        await db.flush()

        try:
            return await self._execute_pipeline(db, story, request)
        except Exception as exc:
            await self._mark_failed(db, story, str(exc))
            raise

    async def reroll_story(
        self,
        story_id: UUID,
        request: RerollRequest,
    ) -> None:
        """Re-run the full generation pipeline on an existing story record.

        Opens its own AsyncSessionLocal session.  Clears all existing pipeline
        data, resets story state, and re-runs the full pipeline.  Intended to
        be registered as a FastAPI BackgroundTask.

        Parameters
        ----------
        story_id : UUID
            The id of the Story record to reroll.
        request : RerollRequest
            Optional overrides for seed, component overrides, target_word_count.

        Returns
        -------
        None
            Result is persisted to the database.
        """
        async with AsyncSessionLocal() as db:
            try:
                story = await self.get_story_by_id(db, story_id)
                if story is None:
                    logger.error("reroll_story: story %s not found", story_id)
                    return

                target_word_count = request.target_word_count or story.target_word_count

                # Clear existing pipeline data
                await self._delete_existing_pipeline_data(db, story.id)

                # Reset story state
                story.status = "planning"
                story.error_message = None
                story.title = None
                story.synopsis = None
                story.generation_seed = None
                story.story_bible = None
                story.actual_word_count = None
                story.target_word_count = target_word_count
                await db.commit()

                # Build a StoryCreateRequest-compatible object for the pipeline
                create_request = StoryCreateRequest(
                    mode=story.mode,
                    seed=request.seed,
                    overrides=request.overrides,
                    target_word_count=target_word_count,
                )

                await self._execute_pipeline(db, story, create_request)
            except Exception as exc:
                logger.error("Reroll failed for story %s: %s", story_id, exc)
                story = await self.get_story_by_id(db, story_id)
                if story is not None:
                    await self._mark_failed(db, story, str(exc))
                raise

    async def reroll_story_sync(
        self,
        db: AsyncSession,
        story: Story,
        request: RerollRequest,
    ) -> Story:
        """Synchronous reroll for backward compatibility (CLI scripts, tests).

        Accepts a caller-provided session and Story ORM object.
        """
        target_word_count = request.target_word_count or story.target_word_count

        # Clear existing pipeline data
        await self._delete_existing_pipeline_data(db, story.id)

        # Reset story state
        story.status = "planning"
        story.error_message = None
        story.title = None
        story.synopsis = None
        story.generation_seed = None
        story.story_bible = None
        story.actual_word_count = None
        story.target_word_count = target_word_count
        await db.commit()

        # Build a StoryCreateRequest-compatible object for the pipeline
        create_request = StoryCreateRequest(
            mode=story.mode,
            seed=request.seed,
            overrides=request.overrides,
            target_word_count=target_word_count,
        )

        try:
            return await self._execute_pipeline(db, story, create_request)
        except Exception as exc:
            await self._mark_failed(db, story, str(exc))
            raise

    async def get_story_by_id(
        self,
        db: AsyncSession,
        story_id: UUID,
    ) -> Story | None:
        """Fetch a story with chapters and scenes eagerly loaded.

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        story_id : UUID
            The story record ID.

        Returns
        -------
        Story | None
            The story with chapters and scenes loaded, or None if not found.
        """
        statement = (
            select(Story)
            .where(Story.id == story_id)
            .options(
                selectinload(Story.chapters)
                .selectinload(StoryChapter.scenes),
                selectinload(Story.component_links),
            )
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Pipeline implementation
    # ------------------------------------------------------------------

    async def _execute_pipeline(
        self,
        db: AsyncSession,
        story: Story,
        request: StoryCreateRequest,
    ) -> Story:
        """Execute the full creation pipeline.

        Returns the populated Story on success.
        """
        # Step 1: Get approved component bundle via RerollService
        sample_request = SampleRequest(
            seed=request.seed,
            overrides=request.overrides,
            target_word_count=request.target_word_count,
        )
        sample_result, _judge_verdict = await self._reroll.get_approved_bundle(
            db, sample_request, story.id
        )
        bundle = sample_result.bundle

        # Step 2: Link components to story
        await self._create_component_links(db, story.id, bundle)

        # Step 3: Compute chapter count
        chapter_count = max(3, request.target_word_count // 5000)

        # Step 4: Generate story plan via PlannerAgent
        plan = await self._planner.plan(
            db, bundle, story.id, request.target_word_count, chapter_count
        )

        # Step 5: Update story with plan data
        story.title = plan.title
        if plan.synopsis is None:
            fallback_synopsis = (
                f"{plan.logline} The story unfolds across {len(plan.chapters)} chapters."
            )
            plan = plan.model_copy(update={"synopsis": fallback_synopsis})
        if plan.chapter_count is None:
            plan = plan.model_copy(update={"chapter_count": len(plan.chapters)})
        if plan.themes is None:
            tag_pool: list[str] = []
            for item in bundle:
                if item.tags:
                    tag_pool.extend(item.tags[:2])  # cap per component
            plan = plan.model_copy(update={"themes": list(dict.fromkeys(tag_pool))[:6]})
        story.synopsis = plan.synopsis
        story.generation_seed = sample_result.seed
        story.story_bible = plan.story_bible
        story.status = "writing"

        # Step 6: Create chapter and scene records
        await self._create_chapters_and_scenes(db, story.id, plan)

        await db.commit()

        # Reload story with chapters and scenes eagerly loaded before passing
        # to write_all_scenes(). The commit above expires all ORM attributes,
        # so accessing story.chapters or chapter.scenes would trigger a lazy
        # load (MissingGreenlet). This reload ensures all relationship
        # collections are populated in-session and unexpired.
        result = await db.execute(
            select(Story)
            .where(Story.id == story.id)
            .options(
                selectinload(Story.chapters).selectinload(StoryChapter.scenes)
            )
        )
        story = result.scalar_one()

        # Step 7: Write scene prose via SceneWriterAgent
        logger.info("Starting scene writing for story %s", story.id)
        await self._scene_service.write_all_scenes(db, story, plan)

        # Step 7.5: Prose quality revision loop
        story.status = "reviewing"
        await db.commit()
        logger.info("Starting prose revision loop for story %s", story.id)
        settings = get_settings()
        try:
            await self._revision_service.run_revision_loop(
                db=db,
                story=story,
                threshold=settings.prose_quality_threshold,
                max_revisions=settings.max_scene_revisions,
            )
        except Exception as exc:
            logger.warning(
                "Revision loop encountered an error for story %s — "
                "continuing to assembly: %s",
                story.id,
                exc,
            )

        # Step 8: Assemble chapter content
        logger.info("Assembling chapters for story %s", story.id)
        await self._chapter_service.assemble_chapters(db, story)

        # Reload with chapters and scenes eagerly loaded so callers can
        # access story.chapters and chapter.scenes after the session closes.
        result = await db.execute(
            select(Story)
            .where(Story.id == story.id)
            .options(
                selectinload(Story.chapters).selectinload(StoryChapter.scenes)
            )
        )
        return result.scalar_one()

    async def _delete_existing_pipeline_data(
        self,
        db: AsyncSession,
        story_id: UUID,
    ) -> None:
        """Delete all pipeline-generated records for a story before reroll.

        Deletes in dependency order:
        1. StoryScene (FK → story_chapters.id)
        2. StoryChapter (FK → stories.id)
        3. StoryComponentLink (FK → stories.id)

        Does not delete the Story record itself.
        """
        # Load chapter IDs first so we can delete their scenes
        chapter_result = await db.execute(
            select(StoryChapter.id).where(StoryChapter.story_id == story_id)
        )
        chapter_ids = [row[0] for row in chapter_result.fetchall()]

        if chapter_ids:
            await db.execute(
                delete(StoryScene).where(StoryScene.chapter_id.in_(chapter_ids))
            )

        await db.execute(
            delete(StoryChapter).where(StoryChapter.story_id == story_id)
        )
        await db.execute(
            delete(StoryComponentLink).where(StoryComponentLink.story_id == story_id)
        )
        await db.commit()

        logger.info(
            "Deleted existing pipeline data for story %s (%d chapters)",
            story_id,
            len(chapter_ids),
        )

    async def _create_component_links(
        self,
        db: AsyncSession,
        story_id: UUID,
        bundle: list[BundleItem],
    ) -> None:
        """Create StoryComponentLink records for every bundle item."""
        links: list[StoryComponentLink] = []
        for item in bundle:
            link = StoryComponentLink(
                story_id=story_id,
                component_id=item.component_id,
                role=item.role,
            )
            links.append(link)
            db.add(link)
        logger.info(
            "Created %d component links for story %s", len(links), story_id
        )

    async def _create_chapters_and_scenes(
        self,
        db: AsyncSession,
        story_id: UUID,
        plan: StoryPlan,
    ) -> None:
        """Create StoryChapter and StoryScene records from the plan."""
        total_scenes = 0

        for chapter_plan in plan.chapters:
            chapter = StoryChapter(
                story_id=story_id,
                chapter_number=chapter_plan.chapter_number,
                title=chapter_plan.title,
                outline=chapter_plan.summary,
                status="pending",
            )
            db.add(chapter)
            await db.flush()

            for scene_plan in chapter_plan.scenes:
                beat = f"{scene_plan.goal} | {scene_plan.conflict} | {scene_plan.outcome}"
                scene = StoryScene(
                    chapter_id=chapter.id,
                    scene_number=scene_plan.scene_number,
                    beat=beat,
                    status="pending",
                    word_count=scene_plan.word_count_target,
                )
                db.add(scene)
                total_scenes += 1

        logger.info(
            "Created %d chapters and %d scenes for story %s",
            len(plan.chapters),
            total_scenes,
            story_id,
        )

    async def _mark_failed(
        self,
        db: AsyncSession,
        story: Story,
        error_message: str,
    ) -> None:
        """Mark a story as failed and record the error.

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        story : Story
            The story record to mark as failed.
        error_message : str
            The error message to store.
        """
        logger.error("Story %s failed: %s", story.id, error_message)
        story.status = "failed"
        story.error_message = error_message
        await db.commit()