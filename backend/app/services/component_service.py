"""Component service: async CRUD operations for component types, components, and constraints.

All methods accept an AsyncSession as the first argument and use SQLAlchemy 2.0
`select()` style throughout.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.component import ComponentType, Component, ComponentConstraint
from backend.app.schemas.component import (
    ComponentTypeCreate,
    ComponentTypeUpdate,
    ComponentCreate,
    ComponentUpdate,
    ConstraintCreate,
    BatchImportFile,
    BatchImportComponent,
)


# ---------------------------------------------------------------------------
# ComponentType
# ---------------------------------------------------------------------------

async def create_component_type(
    db: "AsyncSession", data: ComponentTypeCreate
) -> ComponentType:
    """Insert a new component type."""
    obj = ComponentType(**data.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def get_component_type_by_name(
    db: "AsyncSession", name: str
) -> ComponentType | None:
    """Return component type by name (case-sensitive exact match)."""
    result = await db.execute(
        select(ComponentType).where(ComponentType.name == name)
    )
    return result.scalar_one_or_none()


async def list_component_types(
    db: "AsyncSession", active_only: bool = True
) -> list[ComponentType]:
    """List component types, optionally filtering to active ones."""
    stmt = select(ComponentType)
    if active_only:
        stmt = stmt.where(ComponentType.is_active.is_(True))
    stmt = stmt.order_by(ComponentType.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_component_type(
    db: "AsyncSession", type_id: UUID, data: ComponentTypeUpdate
) -> ComponentType | None:
    """PATCH a component type. Returns None if id not found."""
    obj = await db.get(ComponentType, type_id)
    if obj is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)
    return obj


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

async def create_component(
    db: "AsyncSession", data: ComponentCreate
) -> Component:
    """Insert a new component."""
    obj = Component(**data.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def get_component_by_slug(
    db: "AsyncSession", slug: str
) -> Component | None:
    """Return component by slug (case-sensitive exact match)."""
    result = await db.execute(
        select(Component)
        .options(selectinload(Component.component_type))
        .where(Component.slug == slug)
    )
    return result.scalar_one_or_none()


async def get_component_by_id(
    db: "AsyncSession", component_id: UUID
) -> Component | None:
    """Return component by UUID."""
    return await db.get(Component, component_id)


async def list_components(
    db: "AsyncSession",
    type_name: str | None = None,
    active_only: bool = True,
    tags: list[str] | None = None,
) -> list[Component]:
    """List components with optional filters.

    - type_name: filter by component type name (joins component_types)
    - active_only: filter to is_active=True
    - tags: filter to components that contain ALL provided tags (AND logic)
    """
    stmt = (
        select(Component)
        .options(selectinload(Component.component_type))
    )
    if active_only:
        stmt = stmt.where(Component.is_active.is_(True))
    if type_name is not None:
        stmt = stmt.join(ComponentType).where(ComponentType.name == type_name)
    if tags:
        for tag in tags:
            stmt = stmt.where(Component.tags.contains([tag]))
    stmt = stmt.order_by(Component.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_component(
    db: "AsyncSession", component_id: UUID, data: ComponentUpdate
) -> Component | None:
    """PATCH a component. Returns None if id not found."""
    obj = await db.get(Component, component_id)
    if obj is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)
    return obj


async def deactivate_component(
    db: "AsyncSession", component_id: UUID
) -> bool:
    """Set is_active=False. Returns False if id not found."""
    obj = await db.get(Component, component_id)
    if obj is None:
        return False
    obj.is_active = False
    await db.flush()
    return True


# ---------------------------------------------------------------------------
# ComponentConstraint
# ---------------------------------------------------------------------------

async def create_constraint(
    db: "AsyncSession", data: ConstraintCreate
) -> ComponentConstraint:
    """Insert a constraint rule."""
    obj = ComponentConstraint(**data.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def list_constraints(
    db: "AsyncSession",
    subject_tag: str | None = None,
    active_only: bool = True,
) -> list[ComponentConstraint]:
    """List constraints with optional filters."""
    stmt = select(ComponentConstraint)
    if active_only:
        stmt = stmt.where(ComponentConstraint.is_active.is_(True))
    if subject_tag is not None:
        stmt = stmt.where(ComponentConstraint.subject_tag == subject_tag)
    stmt = stmt.order_by(ComponentConstraint.subject_tag, ComponentConstraint.relation)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def deactivate_constraint(
    db: "AsyncSession", constraint_id: UUID
) -> bool:
    """Set is_active=False on a constraint. Returns False if not found."""
    obj = await db.get(ComponentConstraint, constraint_id)
    if obj is None:
        return False
    obj.is_active = False
    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Batch Import
# ---------------------------------------------------------------------------

async def batch_import(db: "AsyncSession", data: BatchImportFile) -> dict[str, int]:
    """Import component types, components, and constraints in a single transaction.

    Returns summary dict with counts of created and skipped items.
    Rolls back entirely on any non-duplicate error.
    """
    types_created = 0
    components_created = 0
    constraints_created = 0
    skipped = 0

    # Step 1: Create component types (skip duplicates by name)
    type_name_to_id: dict[str, UUID] = {}
    for type_data in data.component_types:
        existing = await get_component_type_by_name(db, type_data.name)
        if existing:
            skipped += 1
            type_name_to_id[type_data.name] = existing.id
        else:
            new_type = await create_component_type(db, type_data)
            type_name_to_id[type_data.name] = new_type.id
            types_created += 1

    # Step 2: Create components (resolve type name to UUID)
    for batch_comp in data.components:
        if batch_comp.component_type not in type_name_to_id:
            raise ValueError(
                f"Unknown component type '{batch_comp.component_type}' for "
                f"component '{batch_comp.slug}'. Type must be created first."
            )
        # Check for duplicate slug
        existing = await get_component_by_slug(db, batch_comp.slug)
        if existing:
            skipped += 1
            continue

        comp_data = ComponentCreate(
            component_type_id=type_name_to_id[batch_comp.component_type],
            name=batch_comp.name,
            slug=batch_comp.slug,
            description=batch_comp.description,
            prompt_fragment=batch_comp.prompt_fragment,
            tags=batch_comp.tags,
            compatibility_tags=batch_comp.compatibility_tags,
            rarity_weight=batch_comp.rarity_weight,
            metadata=batch_comp.metadata,
            is_active=batch_comp.is_active,
        )
        await create_component(db, comp_data)
        components_created += 1

    # Step 3: Create constraints (skip duplicates on subject_tag+relation+object_tag)
    for constraint_data in data.constraints:
        existing_result = await db.execute(
            select(ComponentConstraint).where(
                ComponentConstraint.subject_tag == constraint_data.subject_tag,
                ComponentConstraint.relation == constraint_data.relation,
                ComponentConstraint.object_tag == constraint_data.object_tag,
            )
        )
        if existing_result.scalar_one_or_none():
            skipped += 1
            continue
        await create_constraint(db, constraint_data)
        constraints_created += 1

    return {
        "component_types": types_created,
        "components": components_created,
        "constraints": constraints_created,
        "skipped": skipped,
    }