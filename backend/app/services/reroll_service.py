"""Reroll Service — Phase 4: Sampler + Judge coordination loop.

Coordinates the sampler and judge agents in a retry loop until
a valid bundle is approved or max retries are exhausted.
"""

from __future__ import annotations

from typing import List, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.judge_agent import JudgeAgent
from backend.app.config import settings
from backend.app.schemas.judge import JudgeRequest, JudgeVerdict
from backend.app.schemas.sampler import SampleRequest, SampleResult
from backend.app.services.sampler_service import SamplerService


class RerollError(Exception):
    """Raised when the judge rejects all bundle attempts."""

    def __init__(self, message: str, last_verdict: JudgeVerdict):
        super().__init__(message)
        self.last_verdict = last_verdict


class RerollService:
    """Coordinates sampler + judge in a retry loop."""

    def __init__(self):
        self._sampler = SamplerService()
        self._judge = JudgeAgent()

    async def get_approved_bundle(
        self,
        db: AsyncSession,
        request: SampleRequest,
        story_id: UUID | None = None,
    ) -> Tuple[SampleResult, JudgeVerdict]:
        """Sample bundles until the judge approves or max retries exhausted.

        Returns:
            Tuple of (SampleResult, JudgeVerdict) where verdict.approved is True.

        Raises:
            RerollError: If all attempts are rejected by the judge.
        """
        max_attempts = settings.max_combination_retries
        last_verdict: JudgeVerdict | None = None

        for i in range(1, max_attempts + 1):
            # Sample a bundle
            result = await self._sampler.sample(db, request)

            # Judge the bundle
            verdict = await self._judge.evaluate(
                db,
                JudgeRequest(bundle=result.bundle, attempt_number=i),
                story_id=str(story_id) if story_id else None,
            )

            if verdict.approved:
                return result, verdict

            last_verdict = verdict

            # Update request with judge hints for next attempt
            request = SampleRequest(
                mode=request.mode,
                seed=request.seed,
                overrides=request.overrides,
                target_word_count=request.target_word_count,
                hint_avoid_tags=verdict.suggested_avoid_tags or request.hint_avoid_tags,
                hint_require_tags=verdict.suggested_require_tags or request.hint_require_tags,
            )

        # All attempts exhausted
        if last_verdict is not None:
            raise RerollError(
                f"Judge rejected all {max_attempts} bundle attempts. "
                f"Last score: {last_verdict.score:.2f}",
                last_verdict=last_verdict,
            )

        raise RerollError(
            f"Judge rejected all {max_attempts} bundle attempts.",
            last_verdict=JudgeVerdict(
                approved=False, score=0.0, reasoning="No verdict available",
                weak_roles=[], suggested_avoid_tags=[], suggested_require_tags=[],
            ),
        )