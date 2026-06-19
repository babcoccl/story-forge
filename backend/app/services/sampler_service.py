"""Sampler Service — Phase 3: Component sampling + constraint validation.

Pure deterministic logic. No LLM calls.
"""

import random
import secrets
from typing import Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import settings
from backend.app.models.component import Component, ComponentType, ComponentConstraint
from backend.app.schemas.sampler import BundleItem, SampleRequest, SampleResult


class SamplerError(Exception):
    """Raised when sampling fails after max retries."""


# Required roles and their source component_type names.
# secondary_setting is optional (sampled 60% of the time).
REQUIRED_ROLES = [
    ("protagonist", "character"),
    ("antagonist", "character"),
    ("primary_setting", "setting"),
    ("main_activity", "activity"),
    ("plot_driver", "plot_beat"),
    ("theme", "theme"),
]

OPTIONAL_ROLES = [
    ("secondary_setting", "setting"),
]

ROLE_SAMPLE_PROBABILITY = {
    "secondary_setting": 0.6,
}


class SamplerService:
    """Randomly sample a valid bundle of story components."""

    async def sample(self, db: AsyncSession, request: SampleRequest) -> SampleResult:
        """Main entry point for component sampling.

        Returns a SampleResult with a valid bundle of components.
        Raises SamplerError if no valid bundle found after max retries.
        """
        # Step 1: Initialize seed
        seed = self._init_seed(request.seed)

        # Step 2: Load active components (cached for this call)
        components_by_type = await self._load_active_components(db)

        # Step 3: Load active constraints (cached for this call)
        constraints = await self._load_active_constraints(db)

        # Step 4: Apply overrides
        components_by_type = self._apply_overrides(components_by_type, request.overrides)

        # Step 5-7: Draw, validate, retry
        max_retries = settings.max_combination_retries
        last_violations: List[str] = []

        for attempt in range(1, max_retries + 1):
            bundle = self._weighted_draw(components_by_type)
            is_valid, violations = self._validate_hard_rules(constraints, bundle)

            if is_valid:
                score, soft_warnings = self._score_soft_rules(constraints, bundle)
                return SampleResult(
                    seed=seed,
                    bundle=bundle,
                    constraint_violations=soft_warnings,
                    attempts=attempt,
                    score=score,
                )

            last_violations = violations

        # All retries exhausted
        raise SamplerError(
            f"Failed to sample valid bundle after {max_retries} attempts. "
            f"Last violations: {last_violations}"
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _load_active_components(
        self, db: AsyncSession
    ) -> Dict[str, List[Component]]:
        """Fetch all active components grouped by component_type name.

        Returns dict keyed by type name (e.g. 'character', 'setting').
        """
        result = await db.execute(
            select(Component)
            .join(ComponentType)
            .where(Component.is_active == True)  # noqa: E712
        )
        all_components = result.all()

        grouped: Dict[str, List[Component]] = {}
        for comp in all_components:
            type_name = comp.component_type.name
            grouped.setdefault(type_name, []).append(comp)

        return grouped

    async def _load_active_constraints(self, db: AsyncSession) -> List[ComponentConstraint]:
        """Fetch all active constraints."""
        result = await db.execute(
            select(ComponentConstraint).where(ComponentConstraint.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    def _apply_overrides(
        self,
        components_by_type: Dict[str, List[Component]],
        overrides: Dict[str, str],
    ) -> Dict[str, List[Component]]:
        """Lock specific roles to a component by slug.

        If an override is provided for a role, replace the pool for that
        component_type with only the matching component.
        """
        if not overrides:
            return components_by_type

        for role, slug in overrides.items():
            # Determine the component_type for this role
            type_name = None
            for r, t in REQUIRED_ROLES + OPTIONAL_ROLES:
                if r == role:
                    type_name = t
                    break

            if type_name is None or type_name not in components_by_type:
                continue

            matching = [
                c for c in components_by_type[type_name] if c.slug == slug
            ]
            if matching:
                components_by_type[type_name] = matching

        return components_by_type

    def _weighted_draw(
        self, components_by_type: Dict[str, List[Component]]
    ) -> List[BundleItem]:
        """Draw one component per role using rarity_weight.

        Ensures protagonist != antagonist.
        secondary_setting is drawn 60% of the time.
        """
        bundle: List[BundleItem] = []
        drawn_ids: set = set()

        for role, type_name in REQUIRED_ROLES:
            pool = components_by_type.get(type_name)
            if not pool:
                continue

            # For antagonist, exclude the protagonist if already drawn
            exclude_ids: set | None = None
            if role == "antagonist":
                proto_id = None
                for item in bundle:
                    if item.role == "protagonist":
                        proto_id = item.component_id
                        break
                if proto_id:
                    exclude_ids = {proto_id}

            component = self._draw_one(pool, exclude_ids=exclude_ids)
            if component is None:
                continue

            drawn_ids.add(component.id)
            bundle.append(self._to_bundle_item(component, role))

        # Optional roles
        for role, type_name in OPTIONAL_ROLES:
            probability = ROLE_SAMPLE_PROBABILITY.get(role, 0.5)
            if random.random() < probability:
                pool = components_by_type.get(type_name)
                if not pool:
                    continue

                # Exclude settings already drawn
                exclude_ids = {
                    item.component_id
                    for item in bundle
                    if item.component_type == type_name
                }
                component = self._draw_one(pool, exclude_ids=exclude_ids)
                if component is not None:
                    bundle.append(self._to_bundle_item(component, role))

        return bundle

    def _draw_one(
        self, pool: List[Component], exclude_ids: set | None = None
    ) -> Component | None:
        """Draw a single component using rarity_weight for weighted sampling."""
        if exclude_ids:
            pool = [c for c in pool if c.id not in exclude_ids]

        if not pool:
            return None

        weights = [c.rarity_weight for c in pool]
        return random.choices(population=pool, weights=weights, k=1)[0]

    def _validate_hard_rules(
        self, constraints: List[ComponentConstraint], bundle: List[BundleItem]
    ) -> Tuple[bool, List[str]]:
        """Validate hard constraint rules (excludes, requires).

        Returns (True, []) if valid, (False, [violation_messages]) if not.
        """
        # Collect all compatibility_tags across the bundle
        bundle_tags: set = set()
        for item in bundle:
            bundle_tags.update(item.compatibility_tags)

        violations: List[str] = []

        for constraint in constraints:
            if constraint.relation == "excludes":
                subject_present = constraint.subject_tag in bundle_tags
                object_present = constraint.object_tag in bundle_tags
                if subject_present and object_present:
                    violations.append(
                        f"EXCLUDES violation: '{constraint.subject_tag}' "
                        f"and '{constraint.object_tag}' are mutually exclusive "
                        f"but both appear in the bundle"
                    )
            elif constraint.relation == "requires":
                subject_present = constraint.subject_tag in bundle_tags
                object_present = constraint.object_tag in bundle_tags
                if subject_present and not object_present:
                    violations.append(
                        f"REQUIRES violation: '{constraint.subject_tag}' "
                        f"requires '{constraint.object_tag}' but it is not present"
                    )

        if violations:
            return False, violations
        return True, []

    def _score_soft_rules(
        self, constraints: List[ComponentConstraint], bundle: List[BundleItem]
    ) -> Tuple[float, List[str]]:
        """Score soft constraint rules (prefers, avoids).

        Returns (score_0_to_1, [soft_warning_messages]).
        """
        bundle_tags: set = set()
        for item in bundle:
            bundle_tags.update(item.compatibility_tags)

        score_accumulator = 0.0
        max_possible = 0.0
        soft_warnings: List[str] = []

        for constraint in constraints:
            if constraint.relation == "prefers":
                subject_present = constraint.subject_tag in bundle_tags
                if subject_present:
                    max_possible += constraint.strength
                    if constraint.object_tag in bundle_tags:
                        score_accumulator += constraint.strength

            elif constraint.relation == "avoids":
                subject_present = constraint.subject_tag in bundle_tags
                if subject_present and constraint.object_tag in bundle_tags:
                    penalty = constraint.strength * 0.5
                    score_accumulator -= penalty
                    soft_warnings.append(
                        f"AVOIDS warning: '{constraint.subject_tag}' "
                        f"and '{constraint.object_tag}' should be avoided together "
                        f"(penalty: {penalty:.2f})"
                    )

        # Normalize to 0.0-1.0
        if max_possible > 0:
            normalized = score_accumulator / max_possible
        else:
            normalized = 1.0  # No prefers rules = perfect score by default

        # Clamp to [0.0, 1.0]
        score = max(0.0, min(1.0, normalized))
        return score, soft_warnings

    def _to_bundle_item(self, component: Component, role: str) -> BundleItem:
        """Convert a Component ORM object to a BundleItem schema."""
        return BundleItem(
            role=role,
            component_id=component.id,
            slug=component.slug,
            name=component.name,
            component_type=component.component_type.name,
            tags=component.tags or [],
            compatibility_tags=component.compatibility_tags or [],
            description=component.description or "",
            prompt_fragment=component.prompt_fragment,
        )

    @staticmethod
    def _init_seed(seed: str | None) -> str:
        """Initialize the random seed.

        If seed is None, generate one via secrets.token_hex.
        Returns the seed string actually used.
        """
        if seed is None:
            seed = secrets.token_hex(8)
        random.seed(seed)
        return seed