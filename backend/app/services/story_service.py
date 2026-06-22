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

See SPEC_PHASE_6.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.agents.planner_agent import PlannerAgent
from backend.app.models.story import Story, StoryChapter, StoryComponentLink, StoryScene
from backend.app.schemas.sampler import BundleItem, SampleRequest
from backend.app.schemas.story import StoryCreateRequest, StoryPlan
from backend.app.services.chapter_service import ChapterService
from backend.app.services.reroll_service import RerollService
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_story(
        self,
        db: AsyncSession,
        request: StoryCreateRequest,
    ) -> Story:
        """Create a new story with structured plan from approved components.

        Pipeline:
        1. Insert Story record (status="planning")
        2. Call RerollService.get_approved_bundle()
        3. Create StoryComponentLink records
        4. Call PlannerAgent.plan()
        5. Create StoryChapter + StoryScene records
        6. Update Story with plan data (status="writing")
        7. Call SceneService.write_all_scenes()
        8. Call ChapterService.assemble_chapters()

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        request : StoryCreateRequest
            Client request with mode, seed, overrides, target_word_count.

        Returns
        -------
        Story
            Fully populated Story ORM object with chapters eagerly loaded.

        Raises
        ------
        Exception
            Any exception from the pipeline. On failure, Story status is
            set to "failed" with error_message populated.
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

        # Step 7: Write scene prose via SceneWriterAgent
        logger.info("Starting scene writing for story %s", story.id)
        await self._scene_service.write_all_scenes(db, story, plan)

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