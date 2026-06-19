#!/usr/bin/env python3
"""Batch import components, types, and constraints from a JSON file.

Usage:
    batch_import.py --file PATH [--dry-run]

Reads a JSON file conforming to the BatchImportFile schema and inserts
all component types, components, and constraints into the database.
Use --dry-run to validate without writing.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

from backend.app.db.session import AsyncSessionLocal
from backend.app.schemas.component import BatchImportFile
from backend.app.services import component_service as cs


async def run_import(file_path: Path, dry_run: bool) -> None:
    """Execute the batch import."""
    # Read and validate JSON
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        data_dict: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"JSON parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        data = BatchImportFile.model_validate(data_dict)
    except Exception as exc:
        print("Schema validation error:", file=sys.stderr)
        for err in exc.errors():
            loc = " -> ".join(str(loc) for loc in err.get("loc", []))
            msg = err.get("msg", "")
            print(f"  Field '{loc}': {msg}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        types_count = len(data.component_types)
        components_count = len(data.components)
        constraints_count = len(data.constraints)
        print("=== Dry Run Validation ===")
        print(f"Component Types to create:  {types_count}")
        print(f"Components to create:       {components_count}")
        print(f"Constraints to create:      {constraints_count}")
        print("\nValidation passed. No data written to database.")
        return

    # Perform actual import
    async with AsyncSessionLocal() as db:
        try:
            summary = await cs.batch_import(db, data)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            print(f"Batch import failed: {exc}", file=sys.stderr)
            sys.exit(1)

    print("=== Batch Import Complete ===")
    print(f"Component Types created:  {summary['component_types']}")
    print(f"Components created:       {summary['components']}")
    print(f"Constraints created:      {summary['constraints']}")
    print(f"Skipped (duplicates):     {summary['skipped']}")


def build_parser() -> argparse.ArgumentParser:
    """Build argparse."""
    parser = argparse.ArgumentParser(
        description="Batch import components, types, and constraints from JSON."
    )
    parser.add_argument(
        "--file", required=True, type=Path, help="Path to the JSON import file."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the file without writing to the database.",
    )
    return parser


async def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()
    await run_import(args.file, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())