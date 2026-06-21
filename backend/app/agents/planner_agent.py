"""PlannerAgent — generates a structured story plan from approved components.

See SPEC_PHASE_5.md for full specification.
"""

from __future__ import annotations

import logging
from uuid import UUID

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
                )
                plan = StoryPlan(**result)
                logger.info(
                    "PlannerAgent.plan succeeded on attempt %d  "
                    "(chapters=%d, scenes=%d)",
                    attempt,
                    len(plan.chapters),
                    sum(len(ch.scenes) for ch in plan.chapters),
                )
                return plan
            except AgentError as exc:
                last_error = exc
                logger.warning(
                    "PlannerAgent.plan attempt %d failed: %s", attempt, exc
                )

        raise AgentError(
            f"PlannerAgent failed after {max_attempts} attempts: {last_error}"
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt(chapter_count: int) -> str:
        """Build the system prompt for the planner."""
        return (
            "You are a professional story planner for a creative writing system. "
            "You receive a set of approved story components and must generate a "
            "complete, structured story plan as JSON.\n\n"
            "The plan must:\n"
            "- Have a compelling title and single-sentence logline\n"
            "- Contain exactly {chapter_count} chapters\n"
            "- Each chapter must have 3-5 scenes\n"
            "- Each scene must have a clear goal, conflict, and outcome\n"
            "- The story_bible must capture character states, world details, and tone\n"
            "- Distribute word count evenly across scenes to reach target_word_count total\n"
            "- Use the protagonist and antagonist to drive the central conflict\n"
            "- Ground every scene in the provided setting components\n"
            "- Keep scene goals, conflicts, and outcomes to 1 sentence each\n"
            "- Keep chapter summaries to 2 sentences maximum\n"
            "- story_bible should have 3 keys only: tone, pacing_notes, character_states\n"
            "Respond with a JSON object matching the StoryPlan schema exactly.\n"
            "Respond with a JSON object. Include title, logline, chapters, and story_bible.\n"
            "synopsis, themes, and chapter_count are optional — omit if you are uncertain.\n\n"
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

        scenes_total = chapter_count * 4
        words_per_scene = target_word_count // scenes_total if scenes_total else 0

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
        lines.append(f"  Target word count : {target_word_count}")
        lines.append(f"  Chapter count     : {chapter_count}")
        lines.append("  Scenes per chapter: 3-5")
        lines.append(f"  Words per scene   : ~{words_per_scene} (approximate)")
        lines.append("")
        lines.append("/no_think")
        return "\n".join(lines)