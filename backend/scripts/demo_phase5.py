"""Phase 5 Sprint Demo: Story Planner.

End-to-end demonstration of the Phase 5 story planning pipeline.
Creates a story via the API, displays the generated plan, and verifies
all database records were created correctly.

Requires llama.cpp server running at LLM_BASE_URL.

Usage:
    cd ~/story-forge && .venv/bin/python backend/scripts/demo_phase5.py
"""

import asyncio
import sys
from pathlib import Path

# Bootstrap path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.story import Story, StoryChapter
from backend.app.schemas.story import StoryCreateRequest
from backend.app.services.story_service import StoryService


async def main() -> None:
    """Run the Phase 5 demo."""
    print("=" * 60)
    print("StoryForge Phase 5 Demo: Story Planner")
    print("=" * 60)
    print()
    print("Generating story... (this may take 30-60 seconds)")
    print()

    async with AsyncSessionLocal() as db:
        # Create story via service
        svc = StoryService()
        request = StoryCreateRequest(
            mode="standalone",
            target_word_count=15000,
        )
        story = await svc.create_story(db, request)

        # Fetch with eager loading for display
        result = await db.execute(
            select(Story)
            .where(Story.id == story.id)
            .options(
                selectinload(Story.chapters).selectinload(StoryChapter.scenes),
                selectinload(Story.component_links)
            )
        )
        story = result.scalar_one()

        # Display results
        print("=" * 60)
        print("STORY CREATED")
        print("=" * 60)
        print()
        print(f"Title    : {story.title or '(not set)'}")


        # Display story plan
        total_scenes = sum(len(ch.scenes) for ch in story.chapters)
        print(f"Story Plan ({len(story.chapters)} chapters, {total_scenes} scenes):")
        print()

        for chapter in story.chapters:
            print(f"  Chapter {chapter.chapter_number}: {chapter.title}")
            for scene in chapter.scenes:
                # Parse beat string "goal | conflict | outcome"
                beat_parts = [p.strip() for p in (scene.beat or "").split("|")]
                if len(beat_parts) >= 2:
                    goal = beat_parts[0]
                    conflict = beat_parts[1]
                    print(f"    Scene {scene.scene_number}: [{goal}] | [{conflict}]")
                else:
                    print(f"    Scene {scene.scene_number}: {scene.beat or '(no beat)'}")
            print()

        # Display story bible summary
        if story.story_bible:
            print("Story Bible:")
            bible = story.story_bible
            if "tone" in bible:
                print(f"  Tone   : {bible['tone']}")
            if "pacing_notes" in bible:
                print(f"  Pacing : {bible['pacing_notes']}")
            if "characters" in bible:
                print(f"  Characters: {', '.join(str(c) for c in bible['characters'][:5])}")
            if "world_state" in bible:
                print(f"  World  : {bible['world_state']}")
            print()

        # Summary
        links = story.component_links if story.component_links else []
        print(f"Story ID   : {story.id}")
        print(f"Status     : {story.status}")
        print(f"Seed       : {story.generation_seed or '(not set)'}")
        print(f"DB Records : 1 story, {len(story.chapters)} chapters, "
              f"{total_scenes} scenes, {len(links)} component links")
        print()
        print("Demo complete. Story is ready for Phase 6 (Scene Writer).")


if __name__ == "__main__":
    asyncio.run(main())