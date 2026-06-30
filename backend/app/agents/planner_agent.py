"""PlannerAgent — generates a structured story plan from approved components.

See SPEC_PHASE_5.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base_agent import AgentError, BaseAgent
from backend.app.schemas.sampler import BundleItem
from backend.app.schemas.story import StoryPlan

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """Professional story planner agent.

    Receives approved story components and generates a complete structured
    story plan with title, logline, chapters, scenes, and story bible.
    """

    agent_name = "planner"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        """Dynamic system prompt — overridden at call time via _set_system_prompt()."""
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

    def __init__(self) -> None:
        super().__init__()
        self._system_prompt = ""

    async def plan(
        self,
        db: AsyncSession,
        bundle: list[BundleItem],
        story_id: UUID,
        target_word_count: int,
        chapter_count: int,
    ) -> StoryPlan:
        """Generate a complete story plan from the component bundle.

        Parameters
        ----------
        db : AsyncSession
            Database session for AgentRun logging.
        bundle : list[BundleItem]
            The approved component bundle from RerollService.
        story_id : UUID
            Story record ID for AgentRun logging.
        target_word_count : int
            Desired total word count for the story.
        chapter_count : int
            Number of chapters in the plan.

        Returns
        -------
        StoryPlan
            Fully populated story plan.
        """
        user_message = self._build_user_message(
            bundle, target_word_count, chapter_count
        )
        self.system_prompt = self._build_system_prompt(chapter_count)

        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                result = await self.call_json(
                    db,
                    story_id,
                    None,
                    user_message,
                    schema=StoryPlan.model_json_schema(),
                    max_tokens=16000,
                    enforce_schema=True,
                )
                plan = StoryPlan(**result)
            except ValidationError as ve:
                raise AgentError(
                    f"StoryPlan validation failed on attempt {attempt} "
                    f"({ve.error_count()} errors): {ve}"
                ) from ve
            except AgentError as exc:
                last_error = exc
                logger.warning(
                    "PlannerAgent.plan attempt %d failed: %s", attempt, exc
                )
                continue

            logger.info(
                "PlannerAgent.plan succeeded on attempt %d  "
                "(chapters=%d, scenes=%d)",
                attempt,
                len(plan.chapters),
                sum(len(ch.scenes) for ch in plan.chapters),
            )
            return plan

        raise AgentError(
            f"PlannerAgent failed after {max_attempts} attempts: {last_error}"
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt(chapter_count: int) -> str:
        """Build the system prompt for the planner with structural quality rules."""
        return (
            "You are a professional story architect for a long-form fiction system. "
            "You receive approved story components and produce a complete structured plan as JSON.\n\n"
            "STRUCTURAL RULES — violating any of these produces a weak story:\n\n"
            "1. INVESTIGATION SPINE: Write one sentence in story_bible.investigation_spine "
            "that names how the opening mystery connects to the final confrontation. "
            "Example: 'The Butcher murders connect the arms trade to the Serpent's Hand "
            "through a stolen artifact the cult needs to complete a ritual.' "
            "Every scene must advance, complicate, or resolve this spine. "
            "Do not introduce factions, artifacts, or characters that are not already "
            "connected to this spine.\n\n"
            "2. FACTION DISCIPLINE: List every faction in story_bible.factions. "
            "Each faction must have a single distinct function "
            "(e.g. 'moves weapons', 'seeks the artifact', 'holds the historical key'). "
            "Do not add a new faction after Chapter 1 unless a prior faction's arc is resolved. "
            "Factions must collide — their conflicting functions are where scenes happen.\n\n"
            "3. ARTIFACT CONTINUITY: If any artifact or object drives the plot, define it once "
            "in story_bible.artifacts with a canonical name and physical description. "
            "Never rename or re-describe it. If it changes state (broken, stolen, activated), "
            "update current_state in the continuity digest only — the canonical description stays fixed. "
            "In every scene plan where the artifact is present or referenced, "
            "state_changes must include a line beginning with 'ARTIFACT:' that states "
            "its exact canonical name and current location/holder.\n\n"
            "4. CHARACTER ROLE LOCK: Each character has exactly one role that does not change. "
            "A detective is always a detective. A supernatural outsider may work alongside "
            "police but is never re-introduced as something else. "
            "story_bible.characters must list every named character with their locked role.\n\n"
            "5. CAUSAL SCENE CHAIN: Each scene must include a 'state_changes' field — a list of "
            "concrete facts that are locked true after this scene: artifact location, character "
            "status changes, destroyed objects, made promises, open wounds. "
            "The next scene's 'goal' must directly reference at least one entry from the prior "
            "scene's state_changes. "
            "state_changes must use declarative sentences: 'Jasper is now in custody at the warehouse.' "
            "'The artifact is in Nyx's possession.' Never use vague language like 'tension escalates'.\n\n"
            "6. MYSTERY LAYERING (not replacement): Each act has one dominant question. "
            "Act 1 (Ch 1): Who committed the crime and why? "
            "Act 2 (Ch 2): What larger network enabled it? "
            "Act 3 (Ch 3): What is at stake if the protagonist fails? "
            "Reveals must sharpen the dominant question, not replace it with a different one.\n\n"
            "7. SCENE OBJECTIVE + SETTING BRIEF: Every scene must include both scene_objective "
            "and setting_brief.\n"
            "   - scene_objective: one sentence stating what the protagonist must achieve or learn "
            "before the scene can end (separate from goal — it is the in-scene task).\n"
            "   - setting_brief: a structured object with four subfields that grounds the scene "
            "in a concrete physical location before the plot advances:\n"
            "     * location_name — the specific named place\n"
            "     * time_of_day — e.g. pre-dawn, high noon, candlelit night\n"
            "     * sensory_details — one to two sentences describing dominant sight, sound, and smell "
            "(NOT a location label — the writer needs texture)\n"
            "     * spatial_note — how the protagonist enters or where they stand when the scene opens\n"
            "   The setting_brief must give the writer enough physical detail to open the scene "
            "in-place without summarizing travel.\n\n"
            "JSON REQUIREMENTS:\n"
            "- Exactly {chapter_count} chapters\n"
            "- 3-5 scenes per chapter\n"
            "- Each chapter: chapter_number (int, 1-based), title, summary (2 sentences max), scenes\n"
            "- Each scene: scene_number, scene_objective, goal, conflict, outcome, state_changes, "
            "setting_brief, setting_note, word_count_target\n"
            "- Each scene must use EXACTLY these JSON keys: "
            "scene_number, scene_objective, goal, conflict, outcome, state_changes, setting_brief, setting_note, word_count_target\n"
            "  Do NOT use setting_note_reference, word_count_allocation, or any other variant.\n"
            "- story_bible keys: investigation_spine, tone, pacing_notes, characters, "
            "factions, artifacts\n"
            "- Distribute word count evenly across scenes\n\n"
            "Respond with a JSON object matching the StoryPlan schema. "
            "synopsis, themes, and chapter_count are optional.\n"
        ).format(chapter_count=chapter_count)

    @staticmethod
    def _build_user_message(
        bundle: list[BundleItem],
        target_word_count: int,
        chapter_count: int,
    ) -> str:
        """Build the user message containing component details.

        Extracts components by role from the bundle and formats them
        into a readable prompt for the planner.
        """
        role_map: dict[str, BundleItem | None] = {}
        for item in bundle:
            role = item.role
            if role not in role_map:
                role_map[role] = item

        protagonist = role_map.get("protagonist")
        antagonist = role_map.get("antagonist")
        primary_setting = role_map.get("primary_setting")
        main_activity = role_map.get("main_activity")
        plot_driver = role_map.get("plot_driver")
        theme = role_map.get("theme")
        secondary_setting = role_map.get("secondary_setting")

        lines = ["Story Components:"]

        if protagonist:
            lines.append(
                f"  protagonist   : {protagonist.name} — "
                f"{protagonist.description} [{protagonist.tags}]"
            )
        if antagonist:
            lines.append(
                f"  antagonist    : {antagonist.name} — "
                f"{antagonist.description} [{antagonist.tags}]"
            )
        if primary_setting:
            lines.append(
                f"  primary_setting : {primary_setting.name} — "
                f"{primary_setting.description} [{primary_setting.tags}]"
            )
        if main_activity:
            lines.append(
                f"  main_activity   : {main_activity.name} — "
                f"{main_activity.description} [{main_activity.tags}]"
            )
        if plot_driver:
            lines.append(
                f"  plot_driver     : {plot_driver.name} — "
                f"{plot_driver.description} [{plot_driver.tags}]"
            )
        if theme:
            lines.append(
                f"  theme           : {theme.name} — "
                f"{theme.description} [{theme.tags}]"
            )
        if secondary_setting:
            lines.append(
                f"  secondary_setting : {secondary_setting.name} — "
                f"{secondary_setting.description} [{secondary_setting.tags}]"
            )

        lines.append("")
        lines.append("Requirements:")
        lines.append(f"  Target word count : {target_word_count} total across all scenes")
        lines.append(f"  Chapter count     : {chapter_count}")
        lines.append("  Scenes per chapter: 3-5")
        lines.append("")
        lines.append(
            "Scene JSON keys (exact): "
            "scene_number, scene_objective, goal, conflict, outcome, state_changes, "
            "setting_brief, setting_note, word_count_target"
        )
        lines.append("")
        lines.append("Before writing any scenes, write investigation_spine first.")
        lines.append("Every scene outcome must name a concrete consequence.")
        lines.append(
            "Every scene must include state_changes: a list of 3-5 declarative facts locked true after the scene."
        )
        lines.append(
            "Every scene MUST include setting_brief with all four subfields: "
            "location_name, time_of_day, sensory_details, spatial_note."
        )
        lines.append("")
        lines.append("/no_think")
        return "\n".join(lines)