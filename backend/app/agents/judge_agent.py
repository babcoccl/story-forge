# Judge Agent — evaluates story component bundles

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents import AgentError
from backend.app.agents.base_agent import BaseAgent
from backend.app.schemas.judge import JudgeRequest, JudgeVerdict


class JudgeAgent(BaseAgent):
    """Evaluates whether a set of story components forms a compelling premise."""

    agent_name: str = "judge"

    system_prompt: str = (
        "You are a story premise evaluator for a creative writing system.\n"
        "You receive a set of story components and evaluate whether they form a "
        "compelling, coherent narrative premise.\n\n"
        "Respond with a JSON object with exactly these keys:\n"
        "{\n"
        '  "approved": <bool>,\n'
        '  "score": <float 0.0-1.0>,\n'
        '  "reasoning": "<1-2 sentences>",\n'
        '  "weak_roles": ["<role>", ...],\n'
        '  "suggested_avoid_tags": ["<tag>", ...],\n'
        '  "suggested_require_tags": ["<tag>", ...]\n'
        "}\n\n"
        "Approve if the combination could produce an engaging story (score >= 0.65).\n"
        "Reject if the combination is incoherent, contradictory, or dramatically flat.\n"
        "Be generous — reward creative or unexpected combinations.\n"
        "/no_think"
    )

    async def evaluate(
        self,
        db: AsyncSession,
        request: JudgeRequest,
        story_id: str | None = None,
    ) -> JudgeVerdict:
        """Evaluate a bundle of components and return a structured verdict.

        Retries up to 3 times on AgentError (empty/transient Qwen3 responses).
        """

        # Build user message
        lines: list[str] = []
        for item in request.bundle:
            tags_str = ", ".join(item.tags) if item.tags else "(none)"
            lines.append(f"  {item.role}: {item.name} -- {item.description} [{tags_str}]")

        user_message = (
            "Evaluate the following story component bundle as a narrative premise:\n\n"
            + "\n".join(lines)
            + f"\n\n(attempt {request.attempt_number})"
        )

        last_error: AgentError | None = None
        for attempt in range(1, 4):  # 3 attempts max
            try:
                result = await self.call_json(
                    db=db,
                    story_id=story_id,
                    scene_id=None,
                    user_message=user_message,
                    schema=JudgeVerdict.model_json_schema(),
                )
                return JudgeVerdict(**result)
            except AgentError as exc:
                last_error = exc
                if attempt < 3:
                    await asyncio.sleep(1)
            except Exception as exc:
                raise AgentError(f"Judge evaluation failed: {exc}")

        raise AgentError(f"Judge evaluation failed after 3 attempts: {last_error}")
