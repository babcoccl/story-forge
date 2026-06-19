#!/usr/bin/env python3
"""Manage component constraints: list, create, deactivate, and integrity check.

Usage:
    manage_constraints.py list [--subject TAG] [--relation RELATION] [--inactive]
    manage_constraints.py create --subject TAG --relation RELATION --object TAG
                                  [--strength 0.0-1.0] [--description DESC]
    manage_constraints.py deactivate --id UUID
    manage_constraints.py check
"""

import argparse
import asyncio
import sys
from typing import Dict, List, Set, Tuple

from sqlalchemy import func, select

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.component import Component, ComponentConstraint
from backend.app.schemas.component import ConstraintCreate
from backend.app.services import component_service as cs


VALID_RELATIONS = ["requires", "excludes", "prefers", "avoids"]


async def cmd_list(args: argparse.Namespace) -> None:
    """List constraints with optional filters."""
    async with AsyncSessionLocal() as db:
        constraints: List = await cs.list_constraints(
            db,
            subject_tag=args.subject,
            active_only=not args.inactive,
        )

    if not constraints:
        print("No constraints found.")
        return

    header = f"{'ID':<38} {'SUBJECT':<22} {'RELATION':<12} {'OBJECT':<22} {'STR':<6} {'ACTIVE':<8}"
    separator = "-" * len(header)
    print(header)
    print(separator)
    for c in constraints:
        print(
            f"{str(c.id):<38} "
            f"{c.subject_tag:<22} "
            f"{c.relation:<12} "
            f"{c.object_tag:<22} "
            f"{c.strength:<6.2f} "
            f"{'YES' if c.is_active else 'NO':<8}"
        )


async def cmd_create(args: argparse.Namespace) -> None:
    """Create a new constraint."""
    if args.relation not in VALID_RELATIONS:
        print(f"Relation must be one of: {', '.join(VALID_RELATIONS)}", file=sys.stderr)
        sys.exit(1)

    data = ConstraintCreate(
        subject_tag=args.subject,
        relation=args.relation,
        object_tag=args.object_tag,
        strength=args.strength,
        description=args.description,
    )
    async with AsyncSessionLocal() as db:
        try:
            constraint = await cs.create_constraint(db, data)
            await db.commit()
            print(f"Created constraint: {constraint.subject_tag} {constraint.relation} {constraint.object_tag}")
        except Exception as exc:
            await db.rollback()
            print(f"Error creating constraint: {exc}", file=sys.stderr)
            sys.exit(1)


async def cmd_deactivate(args: argparse.Namespace) -> None:
    """Deactivate a constraint by ID."""
    import uuid
    try:
        constraint_id = uuid.UUID(args.constraint_id)
    except ValueError:
        print(f"Invalid UUID: {args.constraint_id}", file=sys.stderr)
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        ok = await cs.deactivate_constraint(db, constraint_id)
        if ok:
            await db.commit()
            print(f"Deactivated constraint: {args.constraint_id}")
        else:
            print(f"Constraint '{args.constraint_id}' not found.", file=sys.stderr)
            sys.exit(1)


async def cmd_check() -> None:
    """Run constraint integrity report."""
    async with AsyncSessionLocal() as db:

        # 1. Count active constraints by relation type
        result = await db.execute(
            select(ComponentConstraint.relation, func.count())
            .where(ComponentConstraint.is_active.is_(True))
            .group_by(ComponentConstraint.relation)
        )
        counts: Dict[str, int] = dict(result.fetchall())

        # 2. Find orphaned tags
        # Get all active constraints
        result = await db.execute(
            select(ComponentConstraint).where(ComponentConstraint.is_active.is_(True))
        )
        active_constraints: List[ComponentConstraint] = result.scalars().all()

        # Collect all unique tags referenced in constraints
        constraint_tags: Set[str] = set()
        for c in active_constraints:
            constraint_tags.add(c.subject_tag)
            constraint_tags.add(c.object_tag)

        # Get all tags that exist on active components
        result = await db.execute(
            select(Component.tags, Component.compatibility_tags)
            .where(Component.is_active.is_(True))
        )
        component_rows = result.fetchall()

        active_component_tags: Set[str] = set()
        for row in component_rows:
            if row.tags:
                active_component_tags.update(row.tags)
            if row.compatibility_tags:
                active_component_tags.update(row.compatibility_tags)

        orphaned_tags = sorted(constraint_tags - active_component_tags)

        # 3. Find contradictions: same (subject, object) pair with both requires + excludes
        pairs: Dict[Tuple[str, str], Set[str]] = {}
        for c in active_constraints:
            pair = (c.subject_tag, c.object_tag)
            if pair not in pairs:
                pairs[pair] = set()
            pairs[pair].add(c.relation)

        contradictions: List[Tuple[str, str]] = []
        for pair, relations in sorted(pairs.items()):
            if "requires" in relations and "excludes" in relations:
                contradictions.append(pair)

    # Print report
    print("\n=== Constraint Integrity Report ===\n")

    print("Counts by relation:")
    for rel in VALID_RELATIONS:
        print(f"  {rel + ':':<12} {counts.get(rel, 0)}")

    print("\nOrphaned tags (in constraints but no active component has this tag):")
    if orphaned_tags:
        for tag in orphaned_tags:
            print(f"  - {tag}")
    else:
        print("  NONE")

    print("\nContradictions (same pair has both requires + excludes):")
    if contradictions:
        for subj, obj in contradictions:
            print(f"  - ({subj}, {obj})")
    else:
        print("  NONE")

    if not orphaned_tags and not contradictions:
        print("\nConstraint check passed.")
    else:
        print("\nConstraint check completed with issues.")


def build_parser() -> argparse.ArgumentParser:
    """Build argparse sub-commands."""
    parser = argparse.ArgumentParser(
        description="Manage component constraints: list, create, deactivate, check."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List constraints.")
    p_list.add_argument("--subject", default=None, help="Filter by subject tag.")
    p_list.add_argument("--relation", default=None, help="Filter by relation type.")
    p_list.add_argument("--inactive", action="store_true", help="Include inactive constraints.")

    # create
    p_create = sub.add_parser("create", help="Create a new constraint.")
    p_create.add_argument("--subject", required=True, help="Subject tag.")
    p_create.add_argument(
        "--relation", required=True, choices=VALID_RELATIONS, help="Relation type."
    )
    p_create.add_argument("--object", dest="object_tag", required=True, help="Object tag.")
    p_create.add_argument("--strength", type=float, default=1.0, help="Strength (0.0-1.0).")
    p_create.add_argument("--description", default=None, help="Optional description.")

    # deactivate
    p_deact = sub.add_parser("deactivate", help="Deactivate a constraint.")
    p_deact.add_argument("--id", dest="constraint_id", required=True, help="Constraint UUID.")

    # check
    sub.add_parser("check", help="Run constraint integrity report.")

    return parser


async def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        await cmd_list(args)
    elif args.command == "create":
        await cmd_create(args)
    elif args.command == "deactivate":
        await cmd_deactivate(args)
    elif args.command == "check":
        await cmd_check()


if __name__ == "__main__":
    asyncio.run(main())