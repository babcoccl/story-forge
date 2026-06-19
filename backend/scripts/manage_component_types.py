#!/usr/bin/env python3
"""Manage component types: list, create, and deactivate.

Usage:
    manage_component_types.py list
    manage_component_types.py create --name NAME --display-name DISPLAY [--description DESC]
    manage_component_types.py deactivate --name NAME
"""

import argparse
import asyncio
import sys
from typing import List

from backend.app.db.session import AsyncSessionLocal
from backend.app.schemas.component import ComponentTypeCreate, ComponentTypeUpdate
from backend.app.services import component_service as cs


def fmt_bool(value: bool) -> str:
    """Format boolean as YES/NO."""
    return "YES" if value else "NO"


async def cmd_list() -> None:
    """List all component types in a table."""
    async with AsyncSessionLocal() as db:
        types: List = await cs.list_component_types(db, active_only=False)

    if not types:
        print("No component types found.")
        return

    header = f"{'ID':<38} {'NAME':<20} {'DISPLAY NAME':<22} {'ACTIVE':<8}"
    separator = "-" * len(header)
    print(header)
    print(separator)
    for ct in types:
        print(
            f"{str(ct.id):<38} "
            f"{ct.name:<20} "
            f"{(ct.display_name or ''):<22} "
            f"{fmt_bool(ct.is_active):<8}"
        )


async def cmd_create(args: argparse.Namespace) -> None:
    """Create a new component type."""
    data = ComponentTypeCreate(
        name=args.name,
        display_name=args.display_name,
        description=args.description,
    )
    async with AsyncSessionLocal() as db:
        try:
            ct = await cs.create_component_type(db, data)
            await db.commit()
            print(f"Created component type: {ct.name} ({ct.display_name})")
        except Exception as exc:
            await db.rollback()
            print(f"Error creating component type: {exc}", file=sys.stderr)
            sys.exit(1)


async def cmd_deactivate(args: argparse.Namespace) -> None:
    """Deactivate a component type by name."""
    async with AsyncSessionLocal() as db:
        ct = await cs.get_component_type_by_name(db, args.name)
        if not ct:
            print(f"Component type '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        result = await cs.update_component_type(
            db, ct.id, ComponentTypeUpdate(is_active=False)
        )
        if result:
            await db.commit()
            print(f"Deactivated component type: {args.name}")
        else:
            print(f"Failed to deactivate '{args.name}'.", file=sys.stderr)
            sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    """Build argparse sub-commands."""
    parser = argparse.ArgumentParser(
        description="Manage component types: list, create, deactivate."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all component types.")

    p_create = sub.add_parser("create", help="Create a new component type.")
    p_create.add_argument("--name", required=True, help="Type name (snake_case).")
    p_create.add_argument("--display-name", required=True, help="Human-readable name.")
    p_create.add_argument("--description", default=None, help="Optional description.")

    p_deact = sub.add_parser("deactivate", help="Deactivate a component type.")
    p_deact.add_argument("--name", required=True, help="Type name to deactivate.")

    return parser


async def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        await cmd_list()
    elif args.command == "create":
        await cmd_create(args)
    elif args.command == "deactivate":
        await cmd_deactivate(args)


if __name__ == "__main__":
    asyncio.run(main())