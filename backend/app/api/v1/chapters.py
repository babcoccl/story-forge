"""Chapters API — read chapters and scenes for a story.

Endpoints:
  GET /stories/{story_id}/chapters/
  GET /stories/{story_id}/chapters/{chapter_number}
  GET /stories/{story_id}/chapters/{chapter_number}/scenes/{scene_number}

Mounted on the stories router prefix so final paths are:
  /api/v1/stories/{story_id}/chapters/
  /api/v1/stories/{story_id}/chapters/{chapter_number}
  /api/v1/stories/{story_id}/chapters/{chapter_number}/scenes/{scene_number}

See SPEC_PHASE_7.md for full specification.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.story import Story, StoryChapter, StoryScene
from backend.app.schemas.story import (
    ChapterListResponse,
    ChapterResponse,
    SceneResponse,
)

router = APIRouter(
    prefix="/stories/{story_id}/chapters",
    tags=["chapters"],
)


def get_db() -> AsyncSession:
    """Provide a database session for dependency injection."""
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        session.close()


async def _require_story(db: AsyncSession, story_id: UUID) -> Story:
    """Load a Story by id or raise 404."""
    result = await db.execute(select(Story).where(Story.id == story_id))
    story = result.scalar_one_or_none()
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story {story_id} not found",
        )
    return story


@router.get("/", response_model=ChapterListResponse)
async def list_chapters(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChapterListResponse:
    """Return all chapters for a story with prose and nested scenes.

    Parameters
    ----------
    story_id : UUID
        The story record ID.
    db : AsyncSession
        Database session.

    Returns
    -------
    ChapterListResponse
        All chapters ordered by chapter_number, each with nested scenes.

    Raises
    ------
    HTTPException
        404 if story not found.
    """
    await _require_story(db, story_id)

    stmt = (
        select(StoryChapter)
        .where(StoryChapter.story_id == story_id)
        .options(selectinload(StoryChapter.scenes))
        .order_by(StoryChapter.chapter_number)
    )
    result = await db.execute(stmt)
    chapters = result.scalars().all()

    chapter_responses = [
        ChapterResponse(
            id=ch.id,
            chapter_number=ch.chapter_number,
            title=ch.title,
            outline=ch.outline,
            content=ch.content,
            word_count=ch.word_count,
            status=ch.status,
            scenes=[
                SceneResponse(
                    id=sc.id,
                    scene_number=sc.scene_number,
                    beat=sc.beat,
                    content=sc.content,
                    word_count=sc.word_count,
                    status=sc.status,
                    continuity_notes=sc.continuity_notes,
                    revision_count=sc.revision_count,
                )
                for sc in sorted(ch.scenes or [], key=lambda s: s.scene_number)
            ],
        )
        for ch in chapters
    ]

    return ChapterListResponse(
        story_id=story_id,
        chapter_count=len(chapter_responses),
        chapters=chapter_responses,
    )


@router.get("/{chapter_number}", response_model=ChapterResponse)
async def get_chapter(
    story_id: UUID,
    chapter_number: int,
    db: AsyncSession = Depends(get_db),
) -> ChapterResponse:
    """Return a single chapter with full prose and nested scenes.

    Parameters
    ----------
    story_id : UUID
        The story record ID.
    chapter_number : int
        1-based chapter number.
    db : AsyncSession
        Database session.

    Returns
    -------
    ChapterResponse
        The chapter with all scenes nested.

    Raises
    ------
    HTTPException
        404 if story or chapter not found.
    """
    await _require_story(db, story_id)

    stmt = (
        select(StoryChapter)
        .where(
            StoryChapter.story_id == story_id,
            StoryChapter.chapter_number == chapter_number,
        )
        .options(selectinload(StoryChapter.scenes))
    )
    result = await db.execute(stmt)
    chapter = result.scalar_one_or_none()

    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chapter {chapter_number} not found in story {story_id}",
        )

    return ChapterResponse(
        id=chapter.id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        outline=chapter.outline,
        content=chapter.content,
        word_count=chapter.word_count,
        status=chapter.status,
        scenes=[
            SceneResponse(
                id=sc.id,
                scene_number=sc.scene_number,
                beat=sc.beat,
                content=sc.content,
                word_count=sc.word_count,
                status=sc.status,
                continuity_notes=sc.continuity_notes,
                revision_count=sc.revision_count,
            )
            for sc in sorted(chapter.scenes or [], key=lambda s: s.scene_number)
        ],
    )


@router.get("/{chapter_number}/scenes/{scene_number}", response_model=SceneResponse)
async def get_scene(
    story_id: UUID,
    chapter_number: int,
    scene_number: int,
    db: AsyncSession = Depends(get_db),
) -> SceneResponse:
    """Return a single scene by chapter and scene number.

    Parameters
    ----------
    story_id : UUID
        The story record ID.
    chapter_number : int
        1-based chapter number.
    scene_number : int
        1-based scene number within the chapter.
    db : AsyncSession
        Database session.

    Returns
    -------
    SceneResponse
        The scene with prose content.

    Raises
    ------
    HTTPException
        404 if story, chapter, or scene not found.
    """
    await _require_story(db, story_id)

    # Load the chapter to validate it belongs to the story
    chapter_stmt = select(StoryChapter).where(
        StoryChapter.story_id == story_id,
        StoryChapter.chapter_number == chapter_number,
    )
    chapter_result = await db.execute(chapter_stmt)
    chapter = chapter_result.scalar_one_or_none()

    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chapter {chapter_number} not found in story {story_id}",
        )

    scene_stmt = select(StoryScene).where(
        StoryScene.chapter_id == chapter.id,
        StoryScene.scene_number == scene_number,
    )
    scene_result = await db.execute(scene_stmt)
    scene = scene_result.scalar_one_or_none()

    if scene is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_number} not found in chapter {chapter_number}",
        )

    return SceneResponse(
        id=scene.id,
        scene_number=scene.scene_number,
        beat=scene.beat,
        content=scene.content,
        word_count=scene.word_count,
        status=scene.status,
        continuity_notes=scene.continuity_notes,
        revision_count=scene.revision_count,
    )