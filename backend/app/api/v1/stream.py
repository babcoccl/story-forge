"""Generation stream API — SSE endpoint for real-time story generation progress.

Endpoint:
  GET /api/v1/stories/{story_id}/stream

Emits Server-Sent Events as story generation progresses. The client
(EventSource in the browser) receives one event per scene completion, a
chapter_complete event when a chapter finishes, and a terminal assembled
or error event when generation ends.

Implementation is a pure DB polling bridge — it reads StoryStatusResponse
from the database every 3 seconds. It requires zero changes to any agent
or service because SceneService already commits after every scene write.

When Phase 12 moves generation to a background task queue, this endpoint
remains unchanged — only the work location changes.

See SPEC_PHASE_8a.md for full specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.story import Story, StoryChapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stories", tags=["stream"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POLL_INTERVAL_SECONDS = 3
_HEARTBEAT_INTERVAL_SECONDS = 15
_TIMEOUT_SECONDS = 2700  # 45 minutes


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

async def _generation_event_generator(story_id: UUID):
    """Async generator that yields SSE events for story generation progress.

    Polls the database every _POLL_INTERVAL_SECONDS. Tracks previously seen
    scene and chapter statuses to emit delta events only (not repeated events
    for the same scene/chapter).

    Yields dicts with keys: event (str), data (str, JSON-encoded payload).
    EventSourceResponse consumes this format directly.
    """
    seen_complete_scenes: set[tuple[int, int]] = set()  # (chapter_number, scene_number)
    seen_complete_chapters: set[int] = set()            # chapter_number
    elapsed = 0
    heartbeat_elapsed = 0

    # Emit connected event immediately
    yield {
        "event": "connected",
        "data": json.dumps({"story_id": str(story_id)}),
    }

    while elapsed < _TIMEOUT_SECONDS:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS
        heartbeat_elapsed += _POLL_INTERVAL_SECONDS

        async with AsyncSessionLocal() as db:
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
            yield {
                "event": "error",
                "data": json.dumps({
                    "story_id": str(story_id),
                    "error_message": "Story not found",
                }),
            }
            return

        # Compute running word total from completed scenes
        total_words_so_far = sum(
            (sc.word_count or 0)
            for ch in (story.chapters or [])
            for sc in (ch.scenes or [])
            if sc.status == "complete"
        )

        # Emit scene_complete events for newly completed scenes
        for chapter in sorted(story.chapters or [], key=lambda c: c.chapter_number):
            for scene in sorted(chapter.scenes or [], key=lambda s: s.scene_number):
                key = (chapter.chapter_number, scene.scene_number)
                if scene.status == "complete" and key not in seen_complete_scenes:
                    seen_complete_scenes.add(key)
                    yield {
                        "event": "scene_complete",
                        "data": json.dumps({
                            "chapter_number": chapter.chapter_number,
                            "scene_number": scene.scene_number,
                            "word_count": scene.word_count,
                            "total_words_so_far": total_words_so_far,
                        }),
                    }
                    heartbeat_elapsed = 0  # reset heartbeat timer on real event

        # Emit chapter_complete events for newly completed chapters
        for chapter in sorted(story.chapters or [], key=lambda c: c.chapter_number):
            if (
                chapter.status == "complete"
                and chapter.chapter_number not in seen_complete_chapters
            ):
                seen_complete_chapters.add(chapter.chapter_number)
                yield {
                    "event": "chapter_complete",
                    "data": json.dumps({
                        "chapter_number": chapter.chapter_number,
                        "word_count": chapter.word_count,
                    }),
                }
                heartbeat_elapsed = 0

        # Terminal: assembled
        if story.status == "assembled":
            yield {
                "event": "assembled",
                "data": json.dumps({
                    "story_id": str(story_id),
                    "actual_word_count": story.actual_word_count,
                    "chapter_count": len(story.chapters or []),
                }),
            }
            return

        # Terminal: failed
        if story.status == "failed":
            yield {
                "event": "error",
                "data": json.dumps({
                    "story_id": str(story_id),
                    "error_message": story.error_message or "Generation failed",
                }),
            }
            return

        # Heartbeat — keeps the connection alive during long LLM calls
        if heartbeat_elapsed >= _HEARTBEAT_INTERVAL_SECONDS:
            yield {
                "event": "heartbeat",
                "data": json.dumps({"elapsed_seconds": elapsed}),
            }
            heartbeat_elapsed = 0

    # Timeout guard
    yield {
        "event": "error",
        "data": json.dumps({
            "story_id": str(story_id),
            "error_message": f"Generation timed out after {_TIMEOUT_SECONDS // 60} minutes",
        }),
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/{story_id}/stream",
    summary="Stream story generation progress via SSE",
    response_description="Server-Sent Events stream of generation events",
)
async def stream_story_generation(story_id: UUID) -> EventSourceResponse:
    """Open an SSE stream for real-time story generation progress.

    The client connects with EventSource and receives events as generation
    proceeds. The connection is closed by the server when the story reaches
    a terminal state (assembled or failed) or after 45 minutes.

    Events emitted (all data is JSON):
      - connected      — emitted immediately on connection
      - scene_complete — emitted after each scene is written
      - chapter_complete — emitted after each chapter is assembled
      - assembled      — terminal success event
      - error          — terminal failure event (also emitted if story not found)
      - heartbeat      — keepalive, every 15s if no other events fire

    Parameters
    ----------
    story_id : UUID
        The story record ID to stream progress for.

    Returns
    -------
    EventSourceResponse
        An SSE response that streams events until generation completes.
    """
    return EventSourceResponse(
        _generation_event_generator(story_id),
        ping=20,  # sse-starlette built-in ping every 20s as secondary keepalive
    )