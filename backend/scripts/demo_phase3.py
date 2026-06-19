#!/usr/bin/env python
"""Phase 3 Demo — Sampler Engine Live Preview.

Shows plausible story setups being generated from the component database.
Usage: python backend/scripts/demo_phase3.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker


from backend.app.config import settings
from backend.app.schemas.sampler import SampleRequest
from backend.app.services.sampler_service import SamplerError, SamplerService


async def count_constraints(db):
    """Count active constraints by relation type."""
    from backend.app.models.component import ComponentConstraint

    result = await db.execute(
        select(
            ComponentConstraint.relation,
            func.count().label("cnt"),
        )
        .where(ComponentConstraint.is_active == True)  # noqa: E712
        .group_by(ComponentConstraint.relation)
    )
    return result.all()


async def main() -> None:
    print("=== StoryForge Phase 3 Demo: Sampler Engine ===")
    print()

    db_url = settings.database_url
    engine = create_async_engine(db_url, echo=False)

    svc = SamplerService()

    # --- Run 3 independent samples ---
    scores: list = []
    samples_info: list = []

    for i in range(1, 4):
        async with async_session() as db:
            result = await svc.sample(db, SampleRequest())
            scores.append(result.score)
            samples_info.append(result)

            print(f"-- Sample {i} --")
            print(f"  Seed:     {result.seed}")
            print(f"  Score:    {result.score:.2f}")
            print(f"  Attempts: {result.attempts}")
            print()

            for item in result.bundle:
                tags_str = ", ".join(item.tags[:3]) if item.tags else ""
                print(f"  {item.role:<20s}: {item.name:<25s} [{tags_str}]")
            print()

    # --- Constraint summary ---
    async with async_session() as db:
        constraint_counts = await count_constraints(db)

    excludes_count = sum(r[1] for r in constraint_counts if r[0] == "excludes")
    requires_count = sum(r[1] for r in constraint_counts if r[0] == "requires")
    prefers_count = sum(r[1] for r in constraint_counts if r[0] == "prefers")
    avoids_count = sum(r[1] for r in constraint_counts if r[0] == "avoids")

    avg_score = sum(scores) / len(scores) if scores else 0.0

    print("--- Constraint Summary ---")
    print(f"  Hard rules applied:  {excludes_count} excludes, {requires_count} requires")
    print(f"  Soft rules applied:  {prefers_count} prefers, {avoids_count} avoids")
    print(f"  Avg score across 3 samples: {avg_score:.2f}")
    print()

    # --- Override demo ---
    if samples_info:
        first_proto = samples_info[0].bundle[0]
        proto_slug = first_proto.slug

        async with async_session() as db:
            override_result = await svc.sample(
                db, SampleRequest(overrides={"protagonist": proto_slug})
            )

        override_proto = next(
            (i for i in override_result.bundle if i.role == "protagonist"), None
        )

        print("--- Override Demo ---")
        print(f"  Locking protagonist to: {proto_slug}")
        if override_proto:
            print(f"  Result protagonist: {override_proto.name}  [LOCKED]")
        print()

    print("Demo complete.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())