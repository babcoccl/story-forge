#!/usr/bin/env python
"""Phase 4 Demo Script — Judge Agent + Reroll Service.

Demonstrates the judge agent evaluating story component bundles
and the reroll service looping until approval.

Requires llama.cpp server running at settings.llm_base_url.

Usage: python backend/scripts/demo_phase4.py
"""

import sys
from pathlib import Path
from time import perf_counter
from uuid import UUID

# Bootstrap path for script execution from any directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.models.agent import AgentRun
from backend.app.schemas.judge import JudgeRequest, JudgeVerdict
from backend.app.schemas.sampler import SampleRequest, SampleResult
from backend.app.services.reroll_service import RerollError, RerollService
from backend.app.services.sampler_service import SamplerService


async def demo_single_round(db: AsyncSession) -> None:
    """Round 1: Sample + Judge manually."""
    print("\n-- Round 1: Sample + Judge --")
    print("  Sampling bundle...")

    sampler = SamplerService()
    result = await sampler.sample(db, SampleRequest())

    print(f"  Seed: {result.seed}")
    print(f"  Score: {result.score:.2f}")

    from backend.app.agents.judge_agent import JudgeAgent

    judge = JudgeAgent()
    request = JudgeRequest(bundle=result.bundle, attempt_number=1)
    verdict = await judge.evaluate(db, request, story_id=None)

    status = "APPROVED" if verdict.approved else "REJECTED"
    print(f"  Attempt 1 — Judge verdict: {status} (score: {verdict.score:.2f})")
    print(f"  Reasoning: {verdict.reasoning}")

    if verdict.weak_roles:
        print(f"  Weak roles: {', '.join(verdict.weak_roles)}")
    if verdict.suggested_avoid_tags:
        print(f"  Suggested avoid tags: {', '.join(verdict.suggested_avoid_tags)}")
    if verdict.suggested_require_tags:
        print(f"  Suggested require tags: {', '.join(verdict.suggested_require_tags)}")

    print("\n  Approved bundle:")
    for item in result.bundle:
        tags = ", ".join(item.compatibility_tags)
        print(f"    {item.role:<18}: {item.name:<25} [{tags}]")


async def demo_reroll(db: AsyncSession) -> None:
    """Round 2: RerollService demo."""
    print("\n-- Round 2: Reroll Demo --")
    print("  Running RerollService (may take multiple attempts)...")

    reroll_svc = RerollService()

    try:
        result, verdict = await reroll_svc.get_approved_bundle(
            db, SampleRequest(), story_id=None,
        )
    except RerollError as e:
        print(f"  RerollError: {e}")
        print(f"  Last verdict: {e.last_verdict.reasoning}")
        return

    # Re-run to show attempt progression
    print("  Re-running with attempt tracking...")

    sampler = SamplerService()
    from backend.app.agents.judge_agent import JudgeAgent
    judge = JudgeAgent()

    max_attempts = settings.max_combination_retries
    current_request = SampleRequest()

    for attempt in range(1, max_attempts + 1):
        result = await sampler.sample(db, current_request)
        judge_request = JudgeRequest(bundle=result.bundle, attempt_number=attempt)
        verdict = await judge.evaluate(db, judge_request, story_id=None)

        status = "APPROVED" if verdict.approved else "REJECTED"
        print(f"  Attempt {attempt} — {status} (score: {verdict.score:.2f})")

        if verdict.approved:
            print(f"\n  Final: APPROVED after {attempt} attempt(s)")
            print(f"  Reasoning: {verdict.reasoning}")
            break

        # Build next request with hints
        current_request = SampleRequest(
            hint_avoid_tags=verdict.suggested_avoid_tags,
            hint_require_tags=verdict.suggested_require_tags,
        )
    else:
        print(f"\n  Final: Exhausted {max_attempts} attempts without approval")


async def print_agent_run_stats(demo_start: datetime) -> None:
    """Fetch and print agent run stats from DB."""
    print("\n-- Agent Run Log (from DB) --")

    async with AsyncSessionLocal() as db:
        # Total judge runs since demo start
        count_result = await db.execute(
            select(func.count(AgentRun.id)).where(
                AgentRun.agent_name == "judge",
                AgentRun.created_at >= demo_start,
            )
        )
        total_runs = count_result.scalar()

        # Average latency
        avg_result = await db.execute(
            select(func.avg(AgentRun.latency_ms)).where(
                AgentRun.agent_name == "judge",
                AgentRun.created_at >= demo_start,
            )
        )
        avg_latency = avg_result.scalar() or 0

        # Total tokens
        tokens_result = await db.execute(
            select(func.sum(AgentRun.prompt_tokens + AgentRun.completion_tokens)).where(
                AgentRun.agent_name == "judge",
                AgentRun.created_at >= demo_start,
            )
        )
        total_tokens = int(tokens_result.scalar() or 0)

        print(f"  Total judge runs logged: {total_runs}")
        print(f"  Avg LLM latency: {avg_latency:.0f}ms")
        print(f"  Total tokens used: {total_tokens}")


async def main_async() -> None:
    demo_start = datetime.now(timezone.utc)

    print("=== StoryForge Phase 4 Demo: Judge Agent ===")
    print(f"  LLM: {settings.default_model}")
    print(f"  Base URL: {settings.llm_base_url}")

    async with AsyncSessionLocal() as db:
        await demo_single_round(db)
        await demo_reroll(db)

    await print_agent_run_stats(demo_start)

    print("\nDemo complete.")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()