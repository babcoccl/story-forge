"""Phase 7 validation script — import and schema construction only.

Tests:
- All new Phase 7 schemas import and instantiate correctly.
- New router modules import without error.
- StoryService imports without error.
- ruff check is the final step (run manually or via subprocess import check).

Cline must not run any demo or integration script.
This script contains NO asyncio.run(), NO DB connections, NO HTTP calls.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone


def test_new_schemas() -> None:
    """Verify all Phase 7 schemas construct without error."""
    from backend.app.schemas.story import (
        ChapterListResponse,
        ChapterResponse,
        ChapterStatusItem,
        RerollRequest,
        SceneResponse,
        SceneStatusItem,
        StoryListItem,
        StoryListResponse,
        StoryStatusResponse,
    )

    story_id = uuid.uuid4()
    chapter_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    # SceneResponse
    scene_resp = SceneResponse(
        id=scene_id,
        scene_number=1,
        beat="Hero faces danger",
        content="The storm raged outside.",
        word_count=500,
        status="complete",
        continuity_notes=None,
        revision_count=0,
    )
    assert scene_resp.scene_number == 1

    # ChapterResponse
    chapter_resp = ChapterResponse(
        id=chapter_id,
        chapter_number=1,
        title="Chapter One",
        outline="The inciting incident.",
        content="Full prose here.",
        word_count=3000,
        status="complete",
        scenes=[scene_resp],
    )
    assert len(chapter_resp.scenes) == 1

    # ChapterListResponse
    list_resp = ChapterListResponse(
        story_id=story_id,
        chapter_count=1,
        chapters=[chapter_resp],
    )
    assert list_resp.chapter_count == 1

    # SceneStatusItem
    scene_status = SceneStatusItem(scene_number=1, status="complete", word_count=500)
    assert scene_status.status == "complete"

    # ChapterStatusItem
    ch_status = ChapterStatusItem(
        chapter_number=1,
        title="Chapter One",
        status="complete",
        word_count=3000,
        scene_statuses=[scene_status],
    )
    assert len(ch_status.scene_statuses) == 1

    # StoryStatusResponse
    story_status = StoryStatusResponse(
        id=story_id,
        status="assembled",
        title="Test Story",
        actual_word_count=13000,
        error_message=None,
        chapter_statuses=[ch_status],
    )
    assert story_status.status == "assembled"

    # StoryListItem
    list_item = StoryListItem(
        id=story_id,
        title="Test Story",
        mode="standalone",
        status="assembled",
        synopsis="A thrilling tale.",
        target_word_count=15000,
        actual_word_count=13000,
        chapter_count=3,
        created_at=datetime.now(tz=timezone.utc),
    )
    assert list_item.chapter_count == 3

    # StoryListResponse
    story_list = StoryListResponse(
        total=1,
        offset=0,
        limit=20,
        items=[list_item],
    )
    assert story_list.total == 1

    # RerollRequest — all optional
    reroll_empty = RerollRequest()
    assert reroll_empty.seed is None

    reroll_with_seed = RerollRequest(seed="test-seed-42", target_word_count=20000)
    assert reroll_with_seed.target_word_count == 20000

    print("  [OK] All Phase 7 schemas construct correctly")


def test_existing_schemas_preserved() -> None:
    """Verify Phase 5/6 schemas are still importable and constructable."""
    from backend.app.schemas.story import (
        ChapterPlan,
        ScenePlan,
        SceneContext,
        SceneOutput,
        StoryCreateRequest,
        StoryPlan,
        StoryResponse,
    )

    # ScenePlan alias normalization still works
    scene = ScenePlan(
        scene_number=1,
        goal="Establish setting",
        conflict="Protagonist arrives",
        outcome="World is revealed",
        setting_note_reference="Castle courtyard",  # alias — must normalize
        word_count_allocation=1200,                  # alias — must normalize
    )
    assert scene.setting_note == "Castle courtyard"
    assert scene.word_count_target == 1200

    # ChapterPlan requires min 3 scenes; create 3 for valid construction
    scene2 = ScenePlan(
        scene_number=2,
        goal="Develop conflict",
        conflict="Antagonist appears",
        outcome="Tension rises",
    )
    scene3 = ScenePlan(
        scene_number=3,
        goal="Resolve scene",
        conflict="Climax of chapter",
        outcome="Chapter ending",
    )

    # ChapterPlan alias normalization still works
    chapter = ChapterPlan(
        chapter_number=1,
        chapter_title="The Beginning",  # alias — must normalize
        chapter_summary="The story begins.",  # alias — must normalize
        scenes=[scene, scene2, scene3],
    )
    assert chapter.title == "The Beginning"
    assert chapter.summary == "The story begins."

    print("  [OK] Existing Phase 5/6 schemas preserved and alias normalization works")


def test_router_imports() -> None:
    """Verify all router modules import without error."""
    import backend.app.api.v1.stories  # noqa: F401
    import backend.app.api.v1.chapters  # noqa: F401
    import backend.app.api.v1.router  # noqa: F401
    print("  [OK] All router modules import successfully")


def test_service_imports() -> None:
    """Verify StoryService imports without error."""
    from backend.app.services.story_service import StoryService  # noqa: F401
    print("  [OK] StoryService imports successfully")


def main() -> None:
    print("=== Phase 7 Validation ===")
    print()

    tests = [
        ("New Phase 7 schemas", test_new_schemas),
        ("Existing schemas preserved", test_existing_schemas_preserved),
        ("Router imports", test_router_imports),
        ("Service imports", test_service_imports),
    ]

    failed = 0
    for name, fn in tests:
        print(f"Testing: {name}")
        try:
            fn()
        except Exception as exc:
            print(f"  [FAIL] {exc}")
            failed += 1

    print()
    if failed:
        print(f"FAILED: {failed} test(s) failed.")
        sys.exit(1)
    else:
        print("All Phase 7 validation checks passed.")
        print()
        print("Next step (run manually):")
        print("  cd /home/aihub/Code/story-forge")
        print("  .venv/bin/ruff check backend/app/schemas/story.py \\")
        print("                        backend/app/api/v1/stories.py \\")
        print("                        backend/app/api/v1/chapters.py \\")
        print("                        backend/app/api/v1/router.py \\")
        print("                        backend/app/services/story_service.py")


if __name__ == "__main__":
    main()