"""Stories API — create, retrieve, list, reroll, and poll story records.

Phase 5: POST /stories/, GET /stories/{story_id}
Phase 7: GET /stories/, POST /stories/{story_id}/reroll,
         GET /stories/{story_id}/status

See SPEC_PHASE_5.md and SPEC_PHASE_7.md for full specification.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.story import Story, StoryChapter
from backend.app.schemas.story import (
    ChapterStatusItem,
    RerollRequest,
    SceneStatusItem,
    StoryCreateRequest,
    StoryListItem,
    StoryListResponse,
    StoryResponse,
    StoryStatusResponse,
)
from backend.app.services.story_service import StoryService

router = APIRouter(prefix="/stories", tags=["stories"])


def get_db() -> AsyncSession:
    """Provide a database session for dependency injection."""
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Phase 5 endpoints (preserved exactly)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Phase 7: Story list
# ---------------------------------------------------------------------------

@router.get("/", response_model=StoryListResponse)
async def list_stories(
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Max results to return"),
    db: AsyncSession = Depends(get_db),
) -> StoryListResponse:
    """Return a paginated list of story summaries.

    No prose content is included. Safe for dashboard/list views.

    Parameters
    ----------
    offset : int
        Number of records to skip (default 0).
    limit : int
        Max records to return (default 20, max 100).
    db : AsyncSession
        Database session provided by FastAPI dependency injection.

    Returns
    -------
    StoryListResponse
        Paginated list of StoryListItem summaries.
    """
    # Total count
    count_result = await db.execute(select(func.count()).select_from(Story))
    total = count_result.scalar_one()

    # Fetch page with chapters pre-loaded for chapter_count computation
    stmt = (
        select(Story)
        .options(selectinload(Story.chapters))
        .order_by(Story.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    stories = result.scalars().all()

    items = [
        StoryListItem(
            id=s.id,
            title=s.title,
            mode=s.mode,
            status=s.status,
            synopsis=s.synopsis,
            target_word_count=s.target_word_count,
            actual_word_count=s.actual_word_count,
            chapter_count=len(s.chapters) if s.chapters else 0,
            created_at=s.created_at,
        )
        for s in stories
    ]

    return StoryListResponse(total=total, offset=offset, limit=limit, items=items)


# ---------------------------------------------------------------------------
# Phase 7: Generation status polling
# ---------------------------------------------------------------------------

@router.get("/{story_id}/status", response_model=StoryStatusResponse)
async def get_story_status(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StoryStatusResponse:
    """Return lightweight generation status for a story.

    Never loads prose content. Safe to poll at high frequency during generation.

    Parameters
    ----------
    story_id : UUID
        The story record ID.
    db : AsyncSession
        Database session provided by FastAPI dependency injection.

    Returns
    -------
    StoryStatusResponse
        Story status with per-chapter and per-scene status items.

    Raises
    ------
    HTTPException
        404 if story not found.
    """
    stmt = (
        select(Story)
        .where(Story.id == story_id)
        .options(
            selectinload(Story.chapters).selectinload(StoryChapter.scenes)
        )
    )
    result = await db.execute(stmt)
    story = result.scalar_one_or_none()

    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story {story_id} not found",
        )

    chapter_statuses: list[ChapterStatusItem] = []
    for chapter in sorted(story.chapters or [], key=lambda c: c.chapter_number):
        scene_statuses = [
            SceneStatusItem(
                scene_number=sc.scene_number,
                status=sc.status,
                word_count=sc.word_count,
            )
            for sc in sorted(chapter.scenes or [], key=lambda s: s.scene_number)
        ]
        chapter_statuses.append(
            ChapterStatusItem(
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                status=chapter.status,
                word_count=chapter.word_count,
                scene_statuses=scene_statuses,
            )
        )

    return StoryStatusResponse(
        id=story.id,
        status=story.status,
        title=story.title,
        actual_word_count=story.actual_word_count,
        error_message=story.error_message,
        chapter_statuses=chapter_statuses,
    )


# ---------------------------------------------------------------------------
# Phase 7: Reroll
# ---------------------------------------------------------------------------

@router.post(
    "/{story_id}/reroll",
    response_model=StoryResponse,
    status_code=status.HTTP_200_OK,
)
async def reroll_story(
    story_id: UUID,
    request: RerollRequest,
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Re-run the generation pipeline for an existing story.

    Deletes existing component links, chapters, and scenes, then re-samples
    a new bundle and regenerates the full story in-place. The story record's
    id and created_at are preserved.

    Only stories with status in ("assembled", "failed") may be rerolled.
    Stories currently in a generation pipeline (status="planning", "writing")
    return 409 Conflict.

    Parameters
    ----------
    story_id : UUID
        The story record ID.
    request : RerollRequest
        Optional seed, component overrides, and target_word_count.
    db : AsyncSession
        Database session provided by FastAPI dependency injection.

    Returns
    -------
    StoryResponse
        The rerolled story with new chapter_count and scene_count.

    Raises
    ------
    HTTPException
        404 if story not found.
        409 if story is currently generating.
        500 if reroll pipeline fails.
    """
    stmt = select(Story).where(Story.id == story_id)
    result = await db.execute(stmt)
    story = result.scalar_one_or_none()

    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story {story_id} not found",
        )

    if story.status in ("planning", "writing"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Story {story_id} is currently generating (status={story.status!r}). "
                "Wait for generation to complete before rerolling."
            ),
        )

    svc = StoryService()
    try:
        story = await svc.reroll_story(db, story, request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reroll failed: {exc}",
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