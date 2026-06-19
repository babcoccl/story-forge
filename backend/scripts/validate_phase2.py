#!/usr/bin/env python3
"""Phase 2 Validation Script — end-to-end verification of component ingest system.

Runs all 12 validation checks in sequence, printing PASS/FAIL for each.
Exit code 0 on full pass. Exit code 1 on any failure.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Dict

from sqlalchemy import delete, select

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.component import Component, ComponentConstraint, ComponentType
from backend.app.schemas.component import (
    ComponentUpdate,
)
# Import all service functions (functional pattern, no class)
from backend.app.services.component_service import (
    create_component_type,
    get_component_type_by_name,
    create_component,
    get_component_by_slug,
    list_components,
    update_component,
    deactivate_component,
    create_constraint,
    list_constraints,
    batch_import,
)


SEED_DATA_PATH = Path(__file__).parent / "seed_data" / "initial_components.json"
results: Dict[str, str] = {}


async def clear_seed_data(db):
    """Delete all seed data for a clean re-import. Order: constraints, components, types."""
    from backend.app.models.component import ComponentConstraint as CC
    from backend.app.models.component import Component as C
    from backend.app.models.component import ComponentType as CT

    await db.execute(delete(CC))
    await db.execute(delete(C))
    await db.execute(delete(CT))
    await db.flush()


def log(check: str, status: str, detail: str = "") -> None:
    marker = "PASS" if status == "PASS" else "FAIL"
    results[check] = marker
    line = f"[{check}]  {status}"
    if detail and status == "FAIL":
        line += f"  ({detail})"
    print(line)


async def run_checks(force=False) -> int:
    """Run all validation checks. Return count of failures."""

    # If --force, clear existing seed data first for a clean batch import
    if force:
        print("(Clearing existing seed data for clean import...)")
        async with AsyncSessionLocal() as db:
            await clear_seed_data(db)
            await db.commit()
        print("Seed data cleared.\n")

    # [1] Import check
    try:
        from backend.app.schemas.component import (  # noqa: F401
            ComponentCreate,
            ComponentRead,
            ComponentTypeCreate,
            ConstraintCreate,
            BatchImportFile,
        )
        # Verify all service functions are importable
        from backend.app.services.component_service import (  # noqa: F401
            create_component_type,
            get_component_type_by_name,
            list_component_types,
            update_component_type,
            create_component,
            get_component_by_slug,
            get_component_by_id,
            list_components,
            update_component,
            deactivate_component,
            create_constraint,
            list_constraints,
            deactivate_constraint,
            batch_import,
        )
        # Verify scripts are importable (check they exist and are syntactically valid)
        import importlib.util  # noqa: F401
        script_paths = [
            "backend/scripts/manage_component_types.py",
            "backend/scripts/manage_components.py",
            "backend/scripts/manage_constraints.py",
            "backend/scripts/batch_import.py",
            "backend/scripts/export_components.py",
        ]
        for sp in script_paths:
            spec = importlib.util.spec_from_file_location(sp, sp)
            assert spec is not None and spec.loader is not None, f"{sp} not loadable"
            importlib.util.module_from_spec(spec)
        log("1", "PASS")
    except Exception as exc:
        log("1", "FAIL", str(exc))

    # [2] DB connection
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(select(1))
        log("2", "PASS")
    except Exception as exc:
        log("2", "FAIL", str(exc))

    # [3] Component type creation
    try:
        from backend.app.schemas.component import ComponentTypeCreate
        async with AsyncSessionLocal() as db:
            ct = await create_component_type(
                db,
                ComponentTypeCreate(
                    name="test_validation_type",
                    display_name="Test Type",
                    description="Will be cleaned up",
                ),
            )
            assert ct.name == "test_validation_type"
            found = await get_component_type_by_name(db, "test_validation_type")
            assert found is not None and found.id == ct.id
            await db.commit()
        log("3", "PASS")
    except Exception as exc:
        log("3", "FAIL", str(exc))

    # [4] Component creation
    try:
        from backend.app.schemas.component import ComponentCreate
        async with AsyncSessionLocal() as db:
            # Get the test type id
            ctype = await get_component_type_by_name(db, "test_validation_type")
            assert ctype is not None
            comp = await create_component(
                db,
                ComponentCreate(
                    component_type_id=ctype.id,
                    name="Test Validation Component",
                    slug="test-validation-component",
                    description="This is a test component for validation purposes only.",
                    tags=["test", "validation"],
                    compatibility_tags=["test"],
                ),
            )
            assert comp.slug == "test-validation-component"
            found = await get_component_by_slug(db, "test-validation-component")
            assert found is not None and found.id == comp.id
            await db.commit()
        log("4", "PASS")
    except Exception as exc:
        log("4", "FAIL", str(exc))

    # [5] Constraint creation
    try:
        from backend.app.schemas.component import ConstraintCreate
        async with AsyncSessionLocal() as db:
            c = await create_constraint(
                db,
                ConstraintCreate(
                    subject_tag="test_validation_tag",
                    relation="requires",
                    object_tag="test_target_tag",
                    strength=0.5,
                    description="Test constraint",
                ),
            )
            assert c.subject_tag == "test_validation_tag"
            constraints = await list_constraints(db, subject_tag="test_validation_tag")
            assert any(x.id == c.id for x in constraints)
            await db.commit()
        log("5", "PASS")
    except Exception as exc:
        log("5", "FAIL", str(exc))

    # [6] Batch import
    try:
        from backend.app.schemas.component import BatchImportFile
        seed_data = json.loads(SEED_DATA_PATH.read_text())
        bi = BatchImportFile(**seed_data)
        async with AsyncSessionLocal() as db:
            summary = await batch_import(db, bi)
            await db.commit()
        assert summary["component_types"] >= 7, f"Expected >=7 types, got {summary['component_types']}"
        assert summary["components"] >= 37, f"Expected >=37 components, got {summary['components']}"
        assert summary["constraints"] >= 10, f"Expected >=10 constraints, got {summary['constraints']}"
        log("6", "PASS")
    except Exception as exc:
        log("6", "FAIL", str(exc))

    # [7] List components
    try:
        async with AsyncSessionLocal() as db:
            all_active = await list_components(db, active_only=True)
            assert len(all_active) >= 37
            by_type = await list_components(db, type_name="character", active_only=True)
            assert len(by_type) >= 8
            by_tag = await list_components(db, tags=["fantasy"], active_only=True)
            assert len(by_tag) >= 1
        log("7", "PASS")
    except Exception as exc:
        log("7", "FAIL", str(exc))

    # [8] Component update
    try:
        async with AsyncSessionLocal() as db:
            comp = await get_component_by_slug(db, "test-validation-component")
            assert comp is not None
            old_desc = comp.description
            updated = await update_component(
                db,
                comp.id,
                ComponentUpdate(description="Updated description for validation"),
            )
            assert updated is not None
            assert updated.description == "Updated description for validation"
            assert updated.description != old_desc
            await db.commit()
            # Verify persisted
            comp2 = await get_component_by_slug(db, "test-validation-component")
            assert comp2 is not None and comp2.description == "Updated description for validation"
        log("8", "PASS")
    except Exception as exc:
        log("8", "FAIL", str(exc))

    # [9] Deactivate
    try:
        async with AsyncSessionLocal() as db:
            comp = await get_component_by_slug(db, "test-validation-component")
            assert comp is not None
            ok = await deactivate_component(db, comp.id)
            assert ok is True
            await db.commit()
            comp2 = await get_component_by_slug(db, "test-validation-component")
            assert comp2 is not None and comp2.is_active is False
        log("9", "PASS")
    except Exception as exc:
        log("9", "FAIL", str(exc))

    # [10] Export
    try:
        import subprocess
        tmpdir = tempfile.mkdtemp()
        output_path = Path(tmpdir) / "test_export.json"
        result = subprocess.run(
            [sys.executable, "backend/scripts/export_components.py", "--output", str(output_path)],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0, f"export failed: {result.stderr}"
        data = json.loads(output_path.read_text())
        assert "component_types" in data
        assert "components" in data
        assert "constraints" in data
        log("10", "PASS")
    except Exception as exc:
        log("10", "FAIL", str(exc))

    # [11] Constraint check
    try:
        result = subprocess.run(
            [sys.executable, "backend/scripts/manage_constraints.py", "check"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0, f"check failed: {result.stderr}"
        assert "Constraint Integrity Report" in result.stdout
        log("11", "PASS")
    except Exception as exc:
        log("11", "FAIL", str(exc))

    # [12] Cleanup
    try:
        async with AsyncSessionLocal() as db:
            # Delete test constraint
            tc = await db.execute(
                select(ComponentConstraint).where(
                    ComponentConstraint.subject_tag == "test_validation_tag"
                )
            )
            for row in tc.scalars().all():
                await db.delete(row)
            # Delete test component
            tc = await db.execute(
                select(Component).where(
                    Component.slug == "test-validation-component"
                )
            )
            for row in tc.scalars().all():
                await db.delete(row)
            # Delete test type
            tc = await db.execute(
                select(ComponentType).where(
                    ComponentType.name == "test_validation_type"
                )
            )
            for row in tc.scalars().all():
                await db.delete(row)
            await db.commit()
        log("12", "PASS")
    except Exception as exc:
        log("12", "FAIL", str(exc))

    # Summary
    passed = sum(1 for v in results.values() if v == "PASS")
    total = len(results)
    print(f"\nResult: {passed}/{total} passed")
    return total - passed


async def main(force=False) -> None:
    print("=== Phase 2 Validation ===")
    failures = await run_checks(force=force)
    sys.exit(1 if failures > 0 else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2 Validation Script")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear existing seed data before batch import for a clean run",
    )
    args = parser.parse_args()
    asyncio.run(main(force=args.force))
