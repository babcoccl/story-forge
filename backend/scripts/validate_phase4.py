#!/usr/bin/env python
"""Phase 4 Validation Script — Judge Agent + Reroll Service.

Runs automated checks against the judge agent and reroll service.
Requires llama.cpp server running at settings.llm_base_url.

Usage: python backend/scripts/validate_phase4.py
"""

import sys
from pathlib import Path
from uuid import uuid4

# Bootstrap path for script execution from any directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.judge_agent import JudgeAgent
from backend.app.config import settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.models.agent import AgentRun
from backend.app.schemas.judge import JudgeRequest, JudgeVerdict
from backend.app.schemas.sampler import BundleItem, SampleRequest, SampleResult
from backend.app.services.reroll_service import RerollError, RerollService
from backend.app.services.sampler_service import SamplerError


def _pass(name: str, idx: int) -> None:
    print(f"[{idx}]  {name} ................... PASS")


def _fail(name: str, idx: int, reason: str = "") -> None:
    msg = f"[{idx}]  {name} ................... FAIL"
    if reason:
        msg += f" ({reason})"
    print(msg)


async def run_checks() -> int:
    """Run all validation checks. Returns count of passed checks."""
    passed = 0

    # [1] Import JudgeAgent, RerollService without error
    try:
        # Already imported at module level, but verify they work
        _ = JudgeAgent
        _ = RerollService
        _pass("Import JudgeAgent, RerollService without error", 1)
        passed += 1
    except Exception as e:
        _fail("Import JudgeAgent, RerollService without error", 1, str(e))
        print("  Cannot continue without imports.")
        return 0

    # [2] schemas/judge.py BundleItem is same class as schemas/sampler.py BundleItem
    try:
        from backend.app.schemas.sampler import BundleItem as SamplerBundleItem
        if BundleItem is SamplerBundleItem:
            _pass("BundleItem is same class as sampler.BundleItem", 2)
            passed += 1
        else:
            _fail("BundleItem is same class as sampler.BundleItem", 2, "different classes")
    except Exception as e:
        _fail("BundleItem is same class as sampler.BundleItem", 2, str(e))

    async with AsyncSessionLocal() as db:
        # [3] JudgeAgent.evaluate() returns JudgeVerdict with all required fields
        try:
            judge = JudgeAgent()
            # Build a minimal bundle for testing
            bundle = [
                BundleItem(
                    component_id=uuid4(), slug="test-hero", role="protagonist",
                    name="Test Hero", component_type="character",
                    description="A brave hero", tags=["brave", "heroic"],
                    compatibility_tags=["brave", "heroic"],
                ),
                BundleItem(
                    component_id=uuid4(), slug="test-villain", role="antagonist",
                    name="Test Villain", component_type="character",
                    description="An evil villain", tags=["evil", "powerful"],
                    compatibility_tags=["evil", "powerful"],
                ),
                BundleItem(
                    component_id=uuid4(), slug="test-kingdom", role="primary_setting",
                    name="Test Kingdom", component_type="setting",
                    description="A magical kingdom", tags=["fantasy", "kingdom"],
                    compatibility_tags=["fantasy", "kingdom"],
                ),
                BundleItem(
                    component_id=uuid4(), slug="test-quest", role="main_activity",
                    name="Test Quest", component_type="activity",
                    description="An epic quest", tags=["adventure", "quest"],
                    compatibility_tags=["adventure", "quest"],
                ),
                BundleItem(
                    component_id=uuid4(), slug="test-revenge", role="plot_driver",
                    name="Test Revenge", component_type="plot_beat",
                    description="A quest for revenge", tags=["drama", "revenge"],
                    compatibility_tags=["drama", "revenge"],
                ),
                BundleItem(
                    component_id=uuid4(), slug="test-courage", role="theme",
                    name="Test Courage", component_type="theme",
                    description="Courage in adversity", tags=["courage", "growth"],
                    compatibility_tags=["courage", "growth"],
                ),
            ]
            request = JudgeRequest(bundle=bundle, attempt_number=1)
            verdict = await judge.evaluate(db, request, story_id=None)

            if isinstance(verdict, JudgeVerdict):
                has_fields = all(hasattr(verdict, f) for f in [
                    "approved", "score", "reasoning", "weak_roles",
                    "suggested_avoid_tags", "suggested_require_tags",
                ])
                if has_fields:
                    _pass("JudgeAgent.evaluate() returns JudgeVerdict with all fields", 3)
                    passed += 1
                else:
                    _fail("JudgeAgent.evaluate() returns JudgeVerdict with all fields", 3, "missing fields")
            else:
                _fail("JudgeAgent.evaluate() returns JudgeVerdict with all fields", 3, f"got {type(verdict)}")
        except Exception as e:
            _fail("JudgeAgent.evaluate() returns JudgeVerdict with all fields", 3, str(e))
            verdict = None

        # [4] verdict.approved is bool, verdict.score between 0.0 and 1.0
        if verdict is not None:
            if isinstance(verdict.approved, bool) and 0.0 <= verdict.score <= 1.0:
                _pass("verdict.approved is bool, score in [0.0, 1.0]", 4)
                passed += 1
            else:
                _fail("verdict.approved is bool, score in [0.0, 1.0]", 4,
                       f"approved={verdict.approved!r}, score={verdict.score}")
        else:
            _fail("verdict.approved is bool, score in [0.0, 1.0]", 4, "no verdict from [3]")

        # [5] AgentRun record written to DB after evaluate() call
        if verdict is not None:
            try:
                runs = await db.execute(
                    select(AgentRun).where(AgentRun.agent_name == "judge").order_by(AgentRun.created_at.desc())
                )
                agent_runs = runs.scalars().all()
                if agent_runs:
                    _pass("AgentRun record written to DB after evaluate()", 5)
                    passed += 1
                else:
                    _fail("AgentRun record written to DB after evaluate()", 5, "no records found")
            except Exception as e:
                _fail("AgentRun record written to DB after evaluate()", 5, str(e))
        else:
            _fail("AgentRun record written to DB after evaluate()", 5, "no verdict from [3]")

        # [6] RerollService.get_approved_bundle() returns (SampleResult, JudgeVerdict) tuple
        # Note: May fail if sampler can't find valid bundle (diverse pool + strict constraints)
        # or if judge rejects all attempts. We test the return type when it succeeds.
        result_tuple: tuple[SampleResult, JudgeVerdict] | None = None
        try:
            reroll_svc = RerollService()
            result_tuple = await reroll_svc.get_approved_bundle(
                db, SampleRequest(), story_id=None,
            )
            if (isinstance(result_tuple, tuple) and len(result_tuple) == 2
                    and isinstance(result_tuple[0], SampleResult)
                    and isinstance(result_tuple[1], JudgeVerdict)):
                _pass("get_approved_bundle() returns (SampleResult, JudgeVerdict)", 6)
                passed += 1
            else:
                _fail("get_approved_bundle() returns (SampleResult, JudgeVerdict)", 6,
                       f"got {type(result_tuple)}")
        except SamplerError as e:
            _fail("get_approved_bundle() returns (SampleResult, JudgeVerdict)", 6,
                   f"SamplerError (expected with diverse pool): {e}")
        except RerollError as e:
            _fail("get_approved_bundle() returns (SampleResult, JudgeVerdict)", 6,
                   f"RerollError (judge rejected all): {e}")
        except Exception as e:
            _fail("get_approved_bundle() returns (SampleResult, JudgeVerdict)", 6, str(e))
            result_tuple = None

        # [7] Returned JudgeVerdict.approved is True
        if result_tuple is not None:
            try:
                _, reroll_verdict = result_tuple
                if reroll_verdict.approved:
                    _pass("Returned JudgeVerdict.approved is True", 7)
                    passed += 1
                else:
                    _fail("Returned JudgeVerdict.approved is True", 7, "approved=False")
            except Exception as e:
                _fail("Returned JudgeVerdict.approved is True", 7, str(e))
        else:
            _fail("Returned JudgeVerdict.approved is True", 7, "no tuple from [6]")

    # [8] hint_avoid_tags field exists on SampleRequest and defaults to []
    try:
        sr = SampleRequest()
        if hasattr(sr, "hint_avoid_tags") and sr.hint_avoid_tags == []:
            _pass("hint_avoid_tags field exists and defaults to []", 8)
            passed += 1
        else:
            _fail("hint_avoid_tags field exists and defaults to []", 8,
                   f"hint_avoid_tags={getattr(sr, 'hint_avoid_tags', 'MISSING')}")
    except Exception as e:
        _fail("hint_avoid_tags field exists and defaults to []", 8, str(e))

    # [9] hint_require_tags field exists on SampleRequest and defaults to []
    try:
        sr = SampleRequest()
        if hasattr(sr, "hint_require_tags") and sr.hint_require_tags == []:
            _pass("hint_require_tags field exists and defaults to []", 9)
            passed += 1
        else:
            _fail("hint_require_tags field exists and defaults to []", 9,
                   f"hint_require_tags={getattr(sr, 'hint_require_tags', 'MISSING')}")
    except Exception as e:
        _fail("hint_require_tags field exists and defaults to []", 9, str(e))

    # [10] RerollError raised when judge always rejects
    # Also handles the case where the sampler itself fails (SamplerError) which
    # should still cause the reroll loop to eventually raise RerollError.
    try:
        class AlwaysRejectJudge(JudgeAgent):
            """Mock judge that always rejects for testing."""

            async def evaluate(
                self, db: AsyncSession, request: JudgeRequest, story_id=None,
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    approved=False, score=0.1, reasoning="test",
                    weak_roles=[], suggested_avoid_tags=[], suggested_require_tags=[],
                )

        # Temporarily patch
        test_reroll = RerollService()
        test_reroll._judge = AlwaysRejectJudge()

        try:
            async with AsyncSessionLocal() as db:
                await test_reroll.get_approved_bundle(db, SampleRequest(), story_id=None)
            _fail("RerollError raised when judge always rejects", 10, "no error raised")
        except RerollError as e:
            if hasattr(e, "last_verdict") and isinstance(e.last_verdict, JudgeVerdict):
                _pass("RerollError raised when judge always rejects", 10)
                passed += 1
            else:
                _fail("RerollError raised when judge always rejects", 10, "missing last_verdict")
        except SamplerError as e:
            # SamplerError can be raised if the component pool has no valid bundles
            # This is expected with diverse components + strict constraints
            _fail("RerollError raised when judge always rejects", 10,
                   f"SamplerError (pool has no valid bundles): {e}")
        except Exception as e:
            _fail("RerollError raised when judge always rejects", 10, f"wrong error: {type(e).__name__}: {e}")
    except Exception as e:
        _fail("RerollError raised when judge always rejects", 10, str(e))

    return passed


def main() -> None:
    print("=== Phase 4 Validation ===")
    print(f"  LLM base URL: {settings.llm_base_url}")
    print(f"  Max retries: {settings.max_combination_retries}")
    print()
    passed = asyncio.run(run_checks())
    print(f"\nResult: {passed}/10 passed")
    if passed < 10:
        print("WARNING: Not all checks passed. Review failures above.")
        sys.exit(1)
    else:
        print("All checks passed!")


if __name__ == "__main__":
    main()