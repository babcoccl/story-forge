"""Stories API — create and retrieve story records.

First real API endpoint for StoryForge. Provides the entry point for
the story generation pipeline: component sampling, judge approval,
planning, and chapter/scene record creation.

See SPEC_PHASE_5.md for full specification.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.story import Story, StoryChapter
from backend.app.schemas.story import StoryCreateRequest, StoryResponse
from backend.app.services.story_service import StoryService

router = APIRouter(prefix="/stories", tags=["stories"])


def get_db() -> AsyncSession:
    """Provide a synchronous database session for dependency injection.

    Returns a fresh AsyncSession from AsyncSessionLocal.
    Note: This is a generator, not an async generator, so it returns
    a sync context manager wrapper around the async session.
    """
    # FastAPI's Depends() works with sync generators
    # For async endpoints, we use the session directly
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.post(
    "/",
    response_model=StoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_story(
    request: StoryCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Create a new story with structured plan from approved components.

    Parameters
    ----------
    request : StoryCreateRequest
        Client request with mode, seed, overrides, target_word_count.
    db : AsyncSession
        Database session provided by FastAPI dependency injection.

    Returns
    -------
    StoryResponse
        The created story with computed chapter_count and scene_count.

    Raises
    ------
    HTTPException
        500 if story creation fails.
    """
    svc = StoryService()
    try:
        story = await svc.create_story(db, request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Story creation failed: {exc}",
        )

    chapter_count = len(story.chapters) if story.chapters else 0
    scene_count = (
        sum(len(ch.scenes) for ch in story.chapters) if story.chapters else 0
    )

    return StoryResponse(
        id=story.id,
        title=story.title,
        mode=story.mode,
        status=story.status,
        generation_seed=story.generation_seed,
        synopsis=story.synopsis,
        target_word_count=story.target_word_count,
        story_bible=story.story_bible,
        chapter_count=chapter_count,
        scene_count=scene_count,
        created_at=story.created_at,
    )


@router.get("/{story_id}", response_model=StoryResponse)
async def get_story(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Retrieve a story by ID with chapters and scenes loaded.

    Parameters
    ----------
    story_id : UUID
        The story record ID.
    db : AsyncSession
        Database session provided by FastAPI dependency injection.

    Returns
    -------
    StoryResponse
        The story with computed chapter_count and scene_count.

    Raises
    ------
    HTTPException
        404 if story not found.
    """
    statement = (
        select(Story)
        .where(Story.id == story_id)
        .options(
            selectinload(Story.chapters).selectinload(StoryChapter.scenes),
            selectinload(Story.component_links),
        )
    )
    result = await db.execute(statement)
    story = result.scalar_one_or_none()

    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story {story_id} not found",
        )

    chapter_count = len(story.chapters) if story.chapters else 0
    scene_count = (
        sum(len(ch.scenes) for ch in story.chapters) if story.chapters else 0
    )

    return StoryResponse(
        id=story.id,
        title=story.title,
        mode=story.mode,
        status=story.status,
        generation_seed=story.generation_seed,
        synopsis=story.synopsis,
        target_word_count=story.target_word_count,
        story_bible=story.story_bible,
        chapter_count=chapter_count,
        scene_count=scene_count,
        created_at=story.created_at,
    )