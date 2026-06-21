"""Phase 5 Validation Script.

Verifies all Phase 5 requirements:
 [1]  Import PlannerAgent, StoryService, StoryPlan schemas without error
 [2]  PlannerAgent.plan() returns StoryPlan with all required fields
 [3]  StoryPlan.chapters has correct chapter_count
 [4]  Each chapter has 3-5 scenes
 [5]  All scene goals, conflicts, outcomes are non-empty strings
 [6]  StoryService.create_story() inserts Story, StoryChapter, StoryScene records
 [7]  Story record has status="writing" after create_story()
 [8]  StoryComponentLink records exist for all bundle roles
 [9]  POST /api/v1/stories/ returns 201 with StoryResponse JSON
 [10] GET /api/v1/stories/{id} returns the created story

Requires llama.cpp server running for checks 2-8.
"""

import asyncio
import sys
from pathlib import Path

# Bootstrap path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uuid

import httpx

from backend.app.agents.planner_agent import PlannerAgent
from backend.app.db.session import AsyncSessionLocal
from backend.app.main import app
from backend.app.schemas.sampler import BundleItem
from backend.app.schemas.story import (
    ChapterPlan,  # noqa: F401 - validated via import
    ScenePlan,
    StoryCreateRequest,
    StoryPlan,
    StoryResponse,
)
from backend.app.services.story_service import StoryService


async def check_imports() -> bool:
    """[1] Import all Phase 5 modules without error."""
    try:
        # Force imports to validate
        _ = PlannerAgent
        _ = StoryService
        _ = StoryPlan
        _ = ScenePlan
        _ = StoryCreateRequest
        _ = StoryResponse
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


async def check_planner_agent() -> bool:
    """[2-5] PlannerAgent.plan() returns valid StoryPlan."""
    try:
        agent = PlannerAgent()
        async with AsyncSessionLocal() as db:
            # Build a minimal test bundle
            bundle = [
                BundleItem(
                    component_id=uuid.uuid4(),
                    role="protagonist",
                    name="Test Hero",
                    description="A brave adventurer",
                    tags=["brave"],
                ),
                BundleItem(
                    component_id=uuid.uuid4(),
                    role="antagonist",
                    name="Test Villain",
                    description="A cunning foe",
                    tags=["evil"],
                ),
                BundleItem(
                    component_id=uuid.uuid4(),
                    role="primary_setting",
                    name="Test World",
                    description="A fantasy realm",
                    tags=["fantasy"],
                ),
                BundleItem(
                    component_id=uuid.uuid4(),
                    role="main_activity",
                    name="Quest",
                    description="A grand journey",
                    tags=["adventure"],
                ),
                BundleItem(
                    component_id=uuid.uuid4(),
                    role="plot_driver",
                    name="Revenge",
                    description="Seeking justice",
                    tags=["drama"],
                ),
                BundleItem(
                    component_id=uuid.uuid4(),
                    role="theme",
                    name="Redemption",
                    description="Finding forgiveness",
                    tags=["growth"],
                ),
            ]
            test_story_id = uuid.uuid4()
            plan = await agent.plan(
                db=db,
                bundle=bundle,
                story_id=test_story_id,
                target_word_count=15000,
                chapter_count=3,
            )

            # [2] Verify all required fields
            if not all([
                plan.title,
                plan.logline,
                plan.synopsis,
                plan.themes,
                plan.chapters,
                plan.story_bible,
            ]):
                print("  FAIL: Missing required StoryPlan fields")
                return False

            # [3] Verify chapter_count
            if plan.chapter_count != 3:
                print(f"  FAIL: Expected 3 chapters, got {plan.chapter_count}")
                return False
            if len(plan.chapters) != 3:
                print(f"  FAIL: Expected 3 chapter plans, got {len(plan.chapters)}")
                return False

            # [4] Each chapter has 3-5 scenes
            for ch in plan.chapters:
                if not (3 <= len(ch.scenes) <= 5):
                    print(f"  FAIL: Chapter {ch.chapter_number} has {len(ch.scenes)} scenes (expected 3-5)")
                    return False

            # [5] All scene fields non-empty
            for ch in plan.chapters:
                for scene in ch.scenes:
                    if not scene.goal.strip():
                        print(f"  FAIL: Scene {scene.scene_number} has empty goal")
                        return False
                    if not scene.conflict.strip():
                        print(f"  FAIL: Scene {scene.scene_number} has empty conflict")
                        return False
                    if not scene.outcome.strip():
                        print(f"  FAIL: Scene {scene.scene_number} has empty outcome")
                        return False

            return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


async def check_story_service() -> bool:
    """[6-8] StoryService.create_story() creates all required DB records."""
    try:
        async with AsyncSessionLocal() as db:
            svc = StoryService()
            request = StoryCreateRequest(
                mode="standalone",
                target_word_count=15000,
            )
            story = await svc.create_story(db, request)

            # [6] Verify records exist
            if not story.id:
                print("  FAIL: Story has no id")
                return False

            if not story.chapters:
                print("  FAIL: No chapters created")
                return False

            total_scenes = sum(len(ch.scenes) for ch in story.chapters)
            if total_scenes == 0:
                print("  FAIL: No scenes created")
                return False

            # [7] Verify status
            if story.status != "writing":
                print(f"  FAIL: Expected status 'writing', got '{story.status}'")
                return False

            # [8] Verify component links
            from sqlalchemy import select

            from backend.app.models.story import StoryComponentLink

            result = await db.execute(
                select(StoryComponentLink).where(
                    StoryComponentLink.story_id == story.id
                )
            )
            links = result.scalars().all()
            if len(links) < 5:
                print(f"  FAIL: Expected at least 5 component links, got {len(links)}")
                return False

            # Cleanup
            from backend.app.models.story import (
                StoryComponentLink,
            )
            for link in links:
                await db.delete(link)
            for ch in story.chapters:
                for scene in ch.scenes:
                    await db.delete(scene)
                await db.delete(ch)
            await db.delete(story)
            await db.commit()

            return True
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


async def check_api_endpoints() -> bool:
    """[9-10] POST and GET /api/v1/stories/ work correctly."""
    try:
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            # [9] POST /api/v1/stories/
            response = await client.post(
                "/api/v1/stories/",
                json={
                    "mode": "standalone",
                    "target_word_count": 15000,
                },
            )
            if response.status_code != 201:
                print(f"  FAIL: POST returned {response.status_code}, expected 201")
                print(f"  Response: {response.text}")
                return False

            data = response.json()
            story_id = data.get("id")
            if not story_id:
                print("  FAIL: Response missing 'id' field")
                return False

            # [10] GET /api/v1/stories/{id}
            get_response = await client.get(f"/api/v1/stories/{story_id}")
            if get_response.status_code != 200:
                print(f"  FAIL: GET returned {get_response.status_code}, expected 200")
                return False

            get_data = get_response.json()
            if get_data.get("id") != story_id:
                print("  FAIL: GET returned different story id")
                return False

            return True
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main() -> int:
    """Run all validation checks."""
    print("=" * 60)
    print("StoryForge Phase 5 Validation")
    print("=" * 60)

    checks = [
        ("[1] Import PlannerAgent, StoryService, StoryPlan", check_imports),
        ("[2-5] PlannerAgent.plan() returns valid StoryPlan", check_planner_agent),
        ("[6-8] StoryService creates all DB records", check_story_service),
        ("[9-10] API endpoints work correctly", check_api_endpoints),
    ]

    passed = 0
    failed = 0

    for name, check_fn in checks:
        print(f"\n{name}...")
        result = await check_fn()
        if result:
            print("  PASS")
            passed += 1
        else:
            print("  FAIL")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(checks)} checks")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)