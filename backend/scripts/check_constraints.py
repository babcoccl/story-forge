"""Check active constraints in the database."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio
from backend.app.db.session import AsyncSessionLocal
from backend.app.models.component import ComponentConstraint
from sqlalchemy import select


async def main():
    async with AsyncSessionLocal() as db:
        results = await db.execute(
            select(ComponentConstraint).where(ComponentConstraint.is_active == True)
        )
        constraints = results.scalars().all()
        print(f"Total active constraints: {len(constraints)}\n")
        for c in constraints:
            print(f"  [{c.constraint_type}] {c.constraint_name}")
            print(f"    tag_group: {c.tag_group}")
            print(f"    scope: {c.scope}")
            print(f"    max_allowed: {c.max_allowed}")
            print(f"    requires_tag: {c.requires_tag}")
            print(f"    excludes_tag: {c.excludes_tag}")
            print(f"    target_type: {c.target_type}")
            print()


if __name__ == "__main__":
    asyncio.run(main())