"""Stories API — create, retrieve, list, reroll, and poll story records.

Phase 5: POST /stories/, GET /stories/{story_id}
Phase 7: GET /stories/, POST /stories/{story_id}/reroll,
         GET /stories/{story_id}/status
Phase 8 Hotfix 2: Detached pipeline execution via asyncio.create_task()
    (replaces BackgroundTasks to prevent cancellation on navigation).

See SPEC_PHASE_5.md, SPEC_PHASE_7.md, SPEC_PHASE_8_HOTFIX.md and
    SPEC_PHASE_8_HOTFIX2.md for full specification.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.session import get_db
from backend.app.models.agent import AgentRun
from backend.app.models.story import Story, StoryChapter
from backend.app.schemas.agent import (
    AgentRunLogItem,
    AgentRunLogResponse,
    AgentStageSummary,
    AgentTokenBreakdown,
    SceneTimingItem,
    StoryCostResponse,
    StoryPerformanceResponse,
)
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


# ---------------------------------------------------------------------------
# Phase 5 endpoints (preserved) — Phase 8 Hotfix 2: asyncio.create_task
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=StoryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_story(
    request: StoryCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Create a new story record and schedule pipeline execution in the background.

    Uses asyncio.create_task() so the pipeline runs independently of the
    request lifecycle — navigating away cannot cancel it.

    Parameters
    ----------
    request : StoryCreateRequest
        Client request with mode, seed, overrides, target_word_count.
    db : AsyncSession
        Database session provided by FastAPI dependency injection.

    Returns
    -------
    StoryResponse
        The created story record (status="planning", chapter_count=0, scene_count=0).
    """
    svc = StoryService()
    story = await svc.create_story_record(request)

    # Schedule the slow pipeline in the background
    asyncio.create_task(svc.run_pipeline(story.id, request))

    return StoryResponse(
        id=story.id,
        title=story.title,
        mode=story.mode,
        status=story.status,
        generation_seed=story.generation_seed,
        synopsis=story.synopsis,
        target_word_count=story.target_word_count,
        story_bible=story.story_bible,
        chapter_count=0,
        scene_count=0,
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
# Phase 11: Token cost aggregation
# ---------------------------------------------------------------------------

@router.get("/{story_id}/cost", response_model=StoryCostResponse)
async def get_story_cost(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StoryCostResponse:
    """Return aggregated token usage and optional cost estimate for a story.

    Aggregates prompt_tokens and completion_tokens from all AgentRun records
    for the story, grouped by agent_name. Cost estimation is enabled only
    when COST_PER_MILLION_TOKENS > 0 in settings.

    Returns 404 if the story does not exist.
    Returns an empty breakdown (all zeros) if no AgentRun records exist yet.
    """
    from backend.app.config import get_settings
    settings = get_settings()

    # Verify story exists
    story_check = await db.execute(select(Story.id).where(Story.id == story_id))
    if story_check.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story {story_id} not found",
        )

    # Aggregate by agent_name
    stmt = (
        select(
            AgentRun.agent_name,
            func.count(AgentRun.id).label("call_count"),
            func.coalesce(func.sum(AgentRun.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AgentRun.completion_tokens), 0).label("completion_tokens"),
        )
        .where(AgentRun.story_id == story_id)
        .group_by(AgentRun.agent_name)
        .order_by(AgentRun.agent_name)
    )
    result = await db.execute(stmt)
    rows = result.all()

    rate = settings.cost_per_million_tokens
    breakdown: list[AgentTokenBreakdown] = []
    for row in rows:
        total = row.prompt_tokens + row.completion_tokens
        cost = (total / 1_000_000 * rate) if rate > 0 else None
        breakdown.append(
            AgentTokenBreakdown(
                agent_name=row.agent_name,
                call_count=row.call_count,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=total,
                estimated_cost_usd=cost,
            )
        )

    total_prompt = sum(b.prompt_tokens for b in breakdown)
    total_completion = sum(b.completion_tokens for b in breakdown)
    total_tokens = total_prompt + total_completion
    total_cost = (total_tokens / 1_000_000 * rate) if rate > 0 else None

    return StoryCostResponse(
        story_id=story_id,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_tokens=total_tokens,
        estimated_cost_usd=total_cost,
        breakdown=breakdown,
    )


@router.get("/{story_id}/agent-runs", response_model=AgentRunLogResponse)
async def get_story_agent_runs(
    story_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> AgentRunLogResponse:
    """Return paginated AgentRun log for a story, ordered by created_at asc.

    Returns 404 if the story does not exist.
    Returns empty items list if no runs exist yet.
    """
    # Verify story exists
    story_check = await db.execute(select(Story.id).where(Story.id == story_id))
    if story_check.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story {story_id} not found",
        )

    count_result = await db.execute(
        select(func.count(AgentRun.id)).where(AgentRun.story_id == story_id)
    )
    total = count_result.scalar_one()

    stmt = (
        select(AgentRun)
        .where(AgentRun.story_id == story_id)
        .order_by(AgentRun.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()

    items = [
        AgentRunLogItem(
            id=run.id,
            agent_name=run.agent_name,
            status=run.status,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            latency_ms=run.latency_ms,
            retry_count=run.retry_count,
            created_at=run.created_at,
        )
        for run in runs
    ]

    return AgentRunLogResponse(
        story_id=story_id,
        total=total,
        offset=offset,
        limit=limit,
        items=items,
    )


# ---------------------------------------------------------------------------
# Phase 13a: Performance observability
# ---------------------------------------------------------------------------

@router.get("/{story_id}/performance", response_model=StoryPerformanceResponse)
async def get_story_performance(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StoryPerformanceResponse:
    """Return wall-clock and per-scene LLM timing breakdown for a story.

    All data is derived from existing agent_runs rows (agent_name, latency_ms,
    created_at, scene_id). No new database columns or migrations required.

    Returns 404 if the story does not exist.
    Returns empty arrays and null wall-clock if no agent runs exist yet.
    """
    # Verify story exists
    story_check = await db.execute(select(Story.id).where(Story.id == story_id))
    if story_check.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story {story_id} not found",
        )

    # Load all agent runs ordered by created_at ascending
    runs_stmt = (
        select(AgentRun)
        .where(AgentRun.story_id == story_id)
        .order_by(AgentRun.created_at.asc())
    )
    runs_result = await db.execute(runs_stmt)
    all_runs = runs_result.scalars().all()

    # Load all StoryScene records with chapter info and revision_count
    scenes_stmt = (
        select(StoryChapter, StoryChapter.scenes)
        .where(StoryChapter.story_id == story_id)
        .options(selectinload(StoryChapter.scenes))
        .order_by(StoryChapter.chapter_number.asc())
    )
    scenes_result = await db.execute(scenes_stmt)
    chapters_rows = scenes_result.scalars().all()

    # Build scene_id -> (chapter_number, scene_number, revision_count) map
    scene_map: dict[str, tuple[int, int, int]] = {}
    for chapter in chapters_rows:
        for scene in (chapter.scenes or []):
            scene_map[str(scene.id)] = (
                chapter.chapter_number,
                scene.scene_number,
                scene.revision_count,
            )

    # --- Compute totals ---
    total_llm_ms: int = sum(r.latency_ms or 0 for r in all_runs)

    total_wall_clock_ms: int | None = None
    if all_runs:
        first_run = all_runs[0]
        last_run = all_runs[-1]
        wall_clock = (last_run.created_at - first_run.created_at).total_seconds() * 1000
        wall_clock += last_run.latency_ms or 0
        total_wall_clock_ms = int(wall_clock)

    overhead_ms: int | None = None
    if total_wall_clock_ms is not None:
        overhead_ms = total_wall_clock_ms - total_llm_ms

    # --- Build scene_timings ---
    # Group runs by scene_id
    from collections import defaultdict
    runs_by_scene: dict[str, list[AgentRun]] = defaultdict(list)
    for run in all_runs:
        if run.scene_id is not None:
            runs_by_scene[str(run.scene_id)].append(run)

    scene_timings: list[SceneTimingItem] = []
    for sid, scene_runs in runs_by_scene.items():
        # Look up in scene_map
        if sid not in scene_map:
            # Orphaned run — skip with debug log
            continue

        chapter_number, scene_number, revision_count = scene_map[sid]

        # Find latencies by agent_name
        def get_latency(name: str) -> int | None:
            return next(
                (r.latency_ms for r in scene_runs if r.agent_name == name and r.latency_ms is not None),
                None,
            )

        # prose_judge can have two runs per scene
        judge_runs = [
            r for r in scene_runs if r.agent_name == "prose_judge" and r.latency_ms is not None
        ]
        prose_judge_first_ms = judge_runs[0].latency_ms if len(judge_runs) >= 1 else None
        prose_judge_second_ms = judge_runs[1].latency_ms if len(judge_runs) >= 2 else None

        scene_writer_ms = get_latency("scene_writer")
        continuity_ms = get_latency("continuity")
        wordsmith_ms = get_latency("wordsmith")

        total_scene_llm_ms = sum(
            r.latency_ms or 0 for r in scene_runs
        )

        scene_timings.append(
            SceneTimingItem(
                scene_id=sid,
                chapter_number=chapter_number,
                scene_number=scene_number,
                scene_writer_ms=scene_writer_ms,
                continuity_ms=continuity_ms,
                prose_judge_first_ms=prose_judge_first_ms,
                wordsmith_ms=wordsmith_ms,
                prose_judge_second_ms=prose_judge_second_ms,
                total_scene_llm_ms=total_scene_llm_ms,
                was_revised=revision_count > 0,
            )
        )

    # Sort by (chapter_number, scene_number)
    scene_timings.sort(key=lambda s: (s.chapter_number, s.scene_number))

    # --- Build stage_summary ---
    runs_by_agent: dict[str, list[AgentRun]] = defaultdict(list)
    for run in all_runs:
        runs_by_agent[run.agent_name].append(run)

    stage_summary: list[AgentStageSummary] = []
    for agent_name, agent_runs in runs_by_agent.items():
        latencies = [r.latency_ms for r in agent_runs if r.latency_ms is not None]
        if not latencies:
            continue  # skip agents with no non-null latencies

        call_count = len(agent_runs)
        total_ms = sum(latencies)
        avg_ms = int(total_ms / len(latencies))
        min_ms = min(latencies)
        max_ms = max(latencies)
        pct = (total_ms / total_llm_ms * 100) if total_llm_ms > 0 else 0.0

        stage_summary.append(
            AgentStageSummary(
                agent_name=agent_name,
                call_count=call_count,
                total_ms=total_ms,
                avg_ms=avg_ms,
                min_ms=min_ms,
                max_ms=max_ms,
                pct_of_total_llm_time=pct,
            )
        )

    # Sort by total_ms descending
    stage_summary.sort(key=lambda s: s.total_ms, reverse=True)

    return StoryPerformanceResponse(
        story_id=story_id,
        total_wall_clock_ms=total_wall_clock_ms,
        total_llm_ms=total_llm_ms,
        overhead_ms=overhead_ms,
        scene_timings=scene_timings,
        stage_summary=stage_summary,
    )


# ---------------------------------------------------------------------------
# Phase 7: Reroll — Phase 8 Hotfix 2: asyncio.create_task
# ---------------------------------------------------------------------------

@router.post(
    "/{story_id}/reroll",
    response_model=StoryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reroll_story(
    story_id: UUID,
    request: RerollRequest,
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Schedule a reroll for an existing story.

    Deletes existing component links, chapters, and scenes, then re-samples
    a new bundle and regenerates the full story in-place. The story record's
    id and created_at are preserved.

    Only stories with status in ("assembled", "failed") may be rerolled.
    Stories currently in a generation pipeline (status="planning", "writing")
    return 409 Conflict.

    Uses asyncio.create_task() so the pipeline runs independently of the
    request lifecycle.

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
        The current story state (before reroll pipeline runs).

    Raises
    ------
    HTTPException
        404 if story not found.
        409 if story is currently generating.
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

    # Return current state immediately; schedule reroll in background
    chapter_count = len(story.chapters) if story.chapters else 0
    scene_count = (
        sum(len(ch.scenes) for ch in story.chapters) if story.chapters else 0
    )

    asyncio.create_task(StoryService().reroll_story(story_id, request))

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