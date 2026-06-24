from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base_agent import AgentError, BaseAgent

logger: logging.Logger = logging.getLogger(__name__)


class ContinuityAgent(BaseAgent):

    agent_name = "continuity"

    SYSTEM_PROMPT = (
        "You are a narrative continuity tracker for a long-form fiction "
        "generation system. You maintain a compact, factual digest of "
        "story state — not a prose summary. "
        "Your output must have exactly four labelled sections: "
        "CHARACTERS, WORLD STATE, OPEN THREADS, and LAST BEAT. "
        "Be precise and factual. Maximum 350 words total. "
        "Do not write prose. Do not editorialize. Facts only."
    )

    async def update_digest(
        self,
        db: AsyncSession,
        story_id: UUID,
        scene_id: UUID,
        scene_prose: str,
        prior_digest: str,
    ) -> str:
        """Update the continuity digest after a new scene is written.

        Builds a user message from the prior digest and the new scene prose,
        calls the LLM (text response), and returns the updated digest string.

        Parameters
        ----------
        db : AsyncSession
            Active database session.
        story_id : UUID
            The story being written.
        scene_id : UUID
            The scene that was just written.
        scene_prose : str
            The full prose of the scene just written.
        prior_digest : str
            The running digest from the previous scene, or empty string
            for the first scene.

        Returns
        -------
        str
            The updated continuity digest (max 350 words).
            If the LLM call fails, returns prior_digest unchanged.
        """
        prior_text = (
            prior_digest
            if prior_digest
            else "(none — this is the first scene)"
        )

        # Truncate scene prose to 4000 characters to stay within token budget
        prose_excerpt = scene_prose[:4000]

        user_message = (
            f"Prior continuity state:\n{prior_text}\n\n"
            f"New scene just written:\n{prose_excerpt}\n\n"
            "Update the continuity digest to reflect everything that has "
            "now occurred.\n"
            "Output the four sections: CHARACTERS, WORLD STATE, "
            "OPEN THREADS, LAST BEAT.\n"
            "Maximum 350 words."
        )

        try:
            result = await self.call(
                db=db,
                story_id=story_id,
                user_message=user_message,
                max_tokens=600,
            )
            return result.strip()
        except AgentError as exc:
            logger.warning(
                "ContinuityAgent LLM call failed for scene %s — "
                "returning prior digest: %s",
                scene_id,
                exc,
            )
            return prior_digest