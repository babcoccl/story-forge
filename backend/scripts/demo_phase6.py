"""demo_phase6.py — Phase 6 end-to-end demo.

Runs the full story creation pipeline including scene writing and chapter
assembly. Prints a summary of the assembled story.

DEVELOPER RUNS THIS MANUALLY — Cline must never execute this script.

Usage:
    python backend/scripts/demo_phase6.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio

from backend.app.db.session import AsyncSessionLocal
from backend.app.schemas.story import StoryCreateRequest
from backend.app.services.story_service import StoryService


async def main() -> None:
    print("=" * 60)
    print("StoryForge Phase 6 Demo: Scene Writer + Chapter Assembly")
    print("=" * 60)
    print()
    print("Generating story... (this will take several minutes)")
    print("SceneWriterAgent calls the LLM once per scene.")
    print()

    async with AsyncSessionLocal() as db:
        svc = StoryService()
        request = StoryCreateRequest(
            mode="standalone",
            target_word_count=15000,
        )

        try:
            story = await svc.create_story(db, request)
        except Exception as exc:
            print(f"Story generation failed: {exc}")
            raise

    print(f"Story ID    : {story.id}")
    print(f"Title       : {story.title}")
    print(f"Status      : {story.status}")
    print(f"Word count  : {story.actual_word_count}")
    print()

    # Reload story with chapters+scenes in a fresh session so relationships
    # are available even though the original session from create_story closed.
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.app.models.story import Story as StoryModel, StoryChapter

        result = await db.execute(
            select(StoryModel)
            .where(StoryModel.id == story.id)
            .options(
                selectinload(StoryModel.chapters).selectinload(StoryChapter.scenes)
            )
        )
        story_full = result.scalar_one()

        for ch in sorted(story_full.chapters, key=lambda c: c.chapter_number):
            scene_count = len(ch.scenes) if ch.scenes else 0
            print(
                f"  Chapter {ch.chapter_number}: {ch.title!r} "
                f"— {ch.word_count or 0} words, {scene_count} scenes, "
                f"status={ch.status}"
            )
        print()
        if story_full.chapters:
            ch1 = next(
                (c for c in story_full.chapters if c.chapter_number == 1), None
            )
            if ch1 and ch1.content:
                print("First 500 chars of Chapter 1:")
                print(ch1.content[:500])
            elif ch1:
                print("Chapter 1 content is empty — scene writing produced no prose.")

    print("Phase 6 demo complete.")


if __name__ == "__main__":
    asyncio.run(main())