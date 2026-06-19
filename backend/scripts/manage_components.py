#!/usr/bin/env python3
"""Manage components: list, show, create, update, and deactivate.

Usage:
    manage_components.py list [--type TYPE] [--tag TAG] [--inactive]
    manage_components.py show --slug SLUG
    manage_components.py create --type TYPE --name NAME --slug SLUG --description DESC
                                [--tags tag1,tag2] [--compat-tags tag1,tag2] [--weight 1.0]
    manage_components.py update --slug SLUG [--description DESC] [--tags tag1,tag2]
                                [--compat-tags tag1,tag2] [--weight 1.0]
    manage_components.py deactivate --slug SLUG
"""

import argparse
import asyncio
import sys
from typing import List, Optional

from backend.app.db.session import AsyncSessionLocal
from backend.app.schemas.component import ComponentCreate, ComponentUpdate
from backend.app.services import component_service as cs


def fmt_bool(value: bool) -> str:
    """Format boolean as YES/NO."""
    return "YES" if value else "NO"


def parse_tags(value: Optional[str]) -> List[str]:
    """Parse comma-separated tag string into a list."""
    if not value:
        return []
    return [t.strip() for t in value.split(",") if t.strip()]


async def cmd_list(args: argparse.Namespace) -> None:
    """List components with optional filters."""
    tags = parse_tags(args.tag) if args.tag else None
    async with AsyncSessionLocal() as db:
        components: List = await cs.list_components(
            db,
            type_name=args.type,
            active_only=not args.inactive,
            tags=tags,
        )

    if not components:
        print("No components found.")
        return

    header = f"{'SLUG':<30} {'TYPE':<18} {'TAGS':<30} {'WEIGHT':<8} {'ACTIVE':<8}"
    separator = "-" * len(header)
    print(header)
    print(separator)
    for comp in components:
        tags_str = ",".join(comp.tags) if comp.tags else ""
        type_name = comp.component_type.name if comp.component_type else "unknown"
        print(
            f"{comp.slug:<30} "
            f"{type_name:<18} "
            f"{tags_str:<30} "
            f"{comp.rarity_weight:<8.2f} "
            f"{fmt_bool(comp.is_active):<8}"
        )


async def cmd_show(args: argparse.Namespace) -> None:
    """Show full detail for a single component."""
    async with AsyncSessionLocal() as db:
        comp = await cs.get_component_by_slug(db, args.slug)

    if not comp:
        print(f"Component '{args.slug}' not found.", file=sys.stderr)
        sys.exit(1)

    type_name = comp.component_type.name if comp.component_type else "unknown"
    print(f"=== Component: {comp.name} ===")
    print(f"  ID:              {comp.id}")
    print(f"  Slug:            {comp.slug}")
    print(f"  Type:            {type_name}")
    print(f"  Description:     {comp.description}")
    print(f"  Prompt Fragment: {comp.prompt_fragment or '(none)'}")
    print(f"  Tags:            {', '.join(comp.tags) if comp.tags else '(none)'}")
    print(f"  Compat Tags:     {', '.join(comp.compatibility_tags) if comp.compatibility_tags else '(none)'}")
    print(f"  Rarity Weight:   {comp.rarity_weight}")
    print(f"  Metadata:        {comp.metadata or '(none)'}")
    print(f"  Active:          {fmt_bool(comp.is_active)}")
    print(f"  Created:         {comp.created_at}")
    print(f"  Updated:         {comp.updated_at}")


async def cmd_create(args: argparse.Namespace) -> None:
    """Create a new component."""
    # Resolve component type by name
    async with AsyncSessionLocal() as db:
        ct = await cs.get_component_type_by_name(db, args.component_type)
        if not ct:
            print(f"Component type '{args.component_type}' not found.", file=sys.stderr)
            sys.exit(1)

        data = ComponentCreate(
            component_type_id=ct.id,
            name=args.name,
            slug=args.slug,
            description=args.description,
            tags=parse_tags(args.tags),
            compatibility_tags=parse_tags(args.compat_tags),
            rarity_weight=args.weight,
        )
        try:
            comp = await cs.create_component(db, data)
            await db.commit()
            print(f"Created component: {comp.slug} ({comp.name})")
        except Exception as exc:
            await db.rollback()
            print(f"Error creating component: {exc}", file=sys.stderr)
            sys.exit(1)


async def cmd_update(args: argparse.Namespace) -> None:
    """Update an existing component."""
    update_data = ComponentUpdate(
        description=args.description,
        tags=parse_tags(args.tags) if args.tags else None,
        compatibility_tags=parse_tags(args.compat_tags) if args.compat_tags else None,
        rarity_weight=args.weight,
    )
    async with AsyncSessionLocal() as db:
        comp = await cs.get_component_by_slug(db, args.slug)
        if not comp:
            print(f"Component '{args.slug}' not found.", file=sys.stderr)
            sys.exit(1)

        result = await cs.update_component(db, comp.id, update_data)
        if result:
            await db.commit()
            print(f"Updated component: {args.slug}")
        else:
            print(f"Failed to update '{args.slug}'.", file=sys.stderr)
            sys.exit(1)


async def cmd_deactivate(args: argparse.Namespace) -> None:
    """Deactivate a component by slug."""
    async with AsyncSessionLocal() as db:
        comp = await cs.get_component_by_slug(db, args.slug)
        if not comp:
            print(f"Component '{args.slug}' not found.", file=sys.stderr)
            sys.exit(1)
        ok = await cs.deactivate_component(db, comp.id)
        if ok:
            await db.commit()
            print(f"Deactivated component: {args.slug}")
        else:
            print(f"Failed to deactivate '{args.slug}'.", file=sys.stderr)
            sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    """Build argparse sub-commands."""
    parser = argparse.ArgumentParser(
        description="Manage components: list, show, create, update, deactivate."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List components.")
    p_list.add_argument("--type", default=None, help="Filter by component type name.")
    p_list.add_argument("--tag", default=None, help="Filter by tag (comma-separated).")
    p_list.add_argument("--inactive", action="store_true", help="Include inactive components.")

    # show
    p_show = sub.add_parser("show", help="Show component detail.")
    p_show.add_argument("--slug", required=True, help="Component slug.")

    # create
    p_create = sub.add_parser("create", help="Create a new component.")
    p_create.add_argument("--type", dest="component_type", required=True, help="Component type name.")
    p_create.add_argument("--name", required=True, help="Component name.")
    p_create.add_argument("--slug", required=True, help="Component slug.")
    p_create.add_argument("--description", required=True, help="Description (min 10 chars).")
    p_create.add_argument("--tags", default=None, help="Tags (comma-separated).")
    p_create.add_argument("--compat-tags", default=None, help="Compatibility tags (comma-separated).")
    p_create.add_argument("--weight", type=float, default=1.0, help="Rarity weight (0.01-100).")

    # update
    p_update = sub.add_parser("update", help="Update a component.")
    p_update.add_argument("--slug", required=True, help="Component slug.")
    p_update.add_argument("--description", default=None, help="New description.")
    p_update.add_argument("--tags", default=None, help="New tags (comma-separated).")
    p_update.add_argument("--compat-tags", default=None, help="New compat tags (comma-separated).")
    p_update.add_argument("--weight", type=float, default=None, help="New rarity weight.")

    # deactivate
    p_deact = sub.add_parser("deactivate", help="Deactivate a component.")
    p_deact.add_argument("--slug", required=True, help="Component slug.")

    return parser


async def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        await cmd_list(args)
    elif args.command == "show":
        await cmd_show(args)
    elif args.command == "create":
        await cmd_create(args)
    elif args.command == "update":
        await cmd_update(args)
    elif args.command == "deactivate":
        await cmd_deactivate(args)


if __name__ == "__main__":
    asyncio.run(main())