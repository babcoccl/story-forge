#!/usr/bin/env python
"""Phase 4.5 Demo Script — Sampler Hardening + Expanded Seed Data.

Demonstrates the sampler service with expanded component pool,
relaxed fallback, and health check functionality.

Does NOT require llama.cpp server (tests sampler in isolation).

Usage: python backend/scripts/demo_phase45.py
"""

import sys
from pathlib import Path

# Bootstrap path for script execution from any directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import AsyncSessionLocal
from backend.app.schemas.sampler import SampleRequest
from backend.app.services.sampler_service import SamplerService


async def print_component_pool_health(db: AsyncSession) -> None:
    """Print component pool health stats."""
    print("\n-- Component Pool Health --")

    sampler = SamplerService()
    health = await sampler.health_check(db)

    for ctype in ["character", "setting", "activity", "plot_beat", "trait", "clothing", "theme"]:
        count = health.get(ctype, 0)
        print(f"  {ctype:<18}: {count} active")


async def run_single_sample(db: AsyncSession, run_number: int) -> None:
    """Run a single sample and print results."""
    print(f"\n-- Sample Run {run_number} --")

    sampler = SamplerService()
    result = await sampler.sample(db, SampleRequest())

    print(f"  Seed: {result.seed}  |  Attempts: {result.attempts}  |  Violations: {', '.join(result.constraint_violations) if result.constraint_violations else 'none'}")

    role_map = {
        "protagonist": "protagonist",
        "antagonist": "antagonist",
        "primary_setting": "primary_setting",
        "main_activity": "main_activity",
        "plot_driver": "plot_driver",
        "theme": "theme",
    }

    for item in result.bundle:
        tags = ", ".join(item.compatibility_tags[:2])
        label = role_map.get(item.role, item.role)
        print(f"  {label:<18}: {item.name:<25} [{tags}]")


async def main_async() -> None:
    print("=== StoryForge Phase 4.5 Demo: Sampler Hardening ===")

    async with AsyncSessionLocal() as db:
        # Show component pool health
        await print_component_pool_health(db)

        # Run 3 sample iterations
        num_runs = 3
        all_passed = True

        for run in range(1, num_runs + 1):
            try:
                await run_single_sample(db, run)
            except Exception as e:
                print(f"\n  ERROR in Sample Run {run}: {e}")
                all_passed = False

        print(f"\nAll {num_runs} samples completed without SamplerError." if all_passed else "\nSome samples failed.")

    print("Demo complete.")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()