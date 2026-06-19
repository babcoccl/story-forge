#!/usr/bin/env python3
"""Export all active components, types, and constraints to a JSON file.

Usage:
    export_components.py --output PATH

Exports data in BatchImportFile-compatible format for round-trip safety.
If PATH is a directory, the file will be named components_export_YYYYMMDD.json.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import select

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.component import Component, ComponentConstraint, ComponentType


async def export_data(output_path: Path) -> None:
    """Export all active components, types, and constraints to JSON."""
    async with AsyncSessionLocal() as db:
        # Fetch all component types
        result = await db.execute(select(ComponentType))
        all_types = result.scalars().all()
        types_data: List[Dict[str, Any]] = []
        type_name_to_id: Dict[str, str] = {}
        for t in all_types:
            type_name_to_id[t.name] = str(t.id)
            types_data.append({
                "name": t.name,
                "display_name": t.display_name,
                "description": t.description,
                "is_active": t.is_active,
            })

        # Fetch all active components with their types
        result = await db.execute(
            select(Component).where(Component.is_active.is_(True)).order_by(Component.slug)
        )
        active_components = result.scalars().all()
        components_data: List[Dict[str, Any]] = []
        for c in active_components:
            comp_dict: Dict[str, Any] = {
                "name": c.name,
                "slug": c.slug,
                "description": c.description,
                "prompt_fragment": c.prompt_fragment,
                "tags": list(c.tags) if c.tags else [],
                "compatibility_tags": list(c.compatibility_tags) if c.compatibility_tags else [],
                "rarity_weight": c.rarity_weight,
                "metadata": dict(c.metadata_) if c.metadata_ else {},
                "is_active": c.is_active,
            }
            # Resolve type name from mapping
            component_type_id_str = str(c.component_type_id)
            if component_type_id_str in type_name_to_id.values():
                for name, tid in type_name_to_id.items():
                    if tid == component_type_id_str:
                        comp_dict["component_type"] = name
                        break

            components_data.append(comp_dict)

        # Fetch all active constraints
        result = await db.execute(
            select(ComponentConstraint)
            .where(ComponentConstraint.is_active.is_(True))
            .order_by(ComponentConstraint.subject_tag, ComponentConstraint.object_tag)
        )
        active_constraints = result.scalars().all()
        constraints_data: List[Dict[str, Any]] = []
        for c in active_constraints:
            constraints_data.append({
                "subject_tag": c.subject_tag,
                "relation": c.relation,
                "object_tag": c.object_tag,
                "strength": c.strength,
                "description": c.description,
                "is_active": c.is_active,
            })

    # Build export payload
    export_payload: Dict[str, Any] = {
        "component_types": types_data,
        "components": components_data,
        "constraints": constraints_data,
    }

    # Determine output file path
    if output_path.is_dir():
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = output_path / f"components_export_{date_str}.json"
    elif output_path.suffix != ".json":
        output_path = output_path.with_suffix(".json")

    # Write JSON file
    try:
        output_path.write_text(
            json.dumps(export_payload, indent=2, default=str), encoding="utf-8"
        )
    except OSError as exc:
        print(f"Error writing file: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Exported {len(types_data)} types, {len(components_data)} components, "
          f"{len(constraints_data)} constraints to {output_path}")


def build_parser() -> argparse.ArgumentParser:
    """Build argparse."""
    parser = argparse.ArgumentParser(
        description="Export all active components, types, and constraints to JSON."
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Output file path or directory (default: components_export_YYYYMMDD.json)."
    )
    return parser


async def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()
    await export_data(args.output)


if __name__ == "__main__":
    asyncio.run(main())