# Base Agent — LLM client wrapper for all agents
# Handles HTTP calls, token tracking, retries, and AgentRun logging.

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.models.agent import AgentRun

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Base exception for agent failures."""
    pass


class BaseAgent:
    """Abstract base class for all StoryForge agents."""

    agent_name: str = "base"
    system_prompt: str = ""

    def __init__(self) -> None:
        s = get_settings()
        self._client = httpx.AsyncClient(
            base_url=s.llm_base_url,
            headers={"Authorization": f"Bearer {s.llm_api_key}"},
            timeout=httpx.Timeout(s.llm_timeout),
        )
        self._settings = s

    def _build_body(
        self,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> dict:
        body: dict = {
            "model": self._settings.default_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature if temperature is not None else float(self._settings.llm_temperature),
            "max_tokens": max_tokens or self._settings.llm_max_tokens,
        }
        if response_format:
            body["response_format"] = response_format
        return body

    async def call(
        self,
        db: AsyncSession,
        story_id: UUID | None = None,
        scene_id: UUID | None = None,
        user_message: str = "",
        response_format: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """POST to /v1/chat/completions, log to AgentRun, return content string."""
        body = self._build_body(user_message, temperature, max_tokens, response_format)
        start_ms = time.time()
        retry_count = 0

        last_error: AgentError | None = None
        for attempt in range(1, 4):  # 3 retries max
            try:
                resp = await self._client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                # Qwen3 think-tag handling.
                # Three possible structures the model produces:
                #   A) <think>...</think>\nPROSE     — prose after closing tag (normal)
                #   B) <think>PROSE</think>          — prose mistakenly inside tag
                #   C) <think>PROSE (no closing tag) — truncated think block
                #   D) PROSE (no think tags at all)  — ideal, pass through as-is

                if "<think>" in content:
                    # Try case A: extract everything after </think>
                    after_match = re.search(r"</think>(.*)", content, re.DOTALL)
                    if after_match:
                        after_content = after_match.group(1).strip()
                        if after_content:
                            content = after_content
                        else:
                            # Case B: nothing after </think> — extract what's inside
                            inside_match = re.search(
                                r"<think>(.*?)</think>", content, re.DOTALL
                            )
                            content = inside_match.group(1).strip() if inside_match else ""
                    else:
                        # Case C: unclosed <think> — extract everything after the tag
                        content = re.sub(r"<think>", "", content, flags=re.DOTALL).strip()

                latency_ms = int((time.time() - start_ms) * 1000)

                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                # log to DB
                run = AgentRun(
                    agent_name=self.agent_name,
                    story_id=story_id,
                    scene_id=scene_id,
                    status="complete",
                    input_payload={"system": self.system_prompt, "user": user_message},
                    output_payload={"content": content},
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    retry_count=retry_count,
                )
                db.add(run)
                await db.commit()
                return content

            except httpx.ReadTimeout:
                retry_count += 1
                logger.error(
                    "LLM ReadTimeout on attempt %d — "
                    "increase LLM_TIMEOUT in .env (currently %.0fs)",
                    attempt,
                    self._settings.llm_timeout,
                )
                last_error = AgentError(
                    f"LLM timed out after {self._settings.llm_timeout}s. "
                    "Set LLM_TIMEOUT >= 300 in .env and retry."
                )
                break  # Timeout is a config issue — do not retry, surface immediately
            except httpx.HTTPError as exc:
                retry_count += 1
                last_error = AgentError(f"HTTP error on attempt {attempt}: {exc}")
                if attempt < 3:
                    await asyncio.sleep(2 ** (attempt - 1))
                else:
                    break

        # final failure
        latency_ms = int((time.time() - start_ms) * 1000)
        run = AgentRun(
            agent_name=self.agent_name,
            story_id=story_id,
            scene_id=scene_id,
            status="failed",
            input_payload={"system": self.system_prompt, "user": user_message},
            output_payload={"error": str(last_error)},
            latency_ms=latency_ms,
            retry_count=retry_count,
        )
        db.add(run)
        await db.commit()
        raise last_error or AgentError("LLM call failed")

    async def call_json(
        self,
        db: AsyncSession,
        story_id: UUID | None = None,
        scene_id: UUID | None = None,
        user_message: str = "",
        schema: dict | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Call LLM with JSON response format, parse and return dict."""
        rf = {"type": "json_object"}
        raw = await self.call(
            db=db,
            story_id=story_id,
            scene_id=scene_id,
            user_message=user_message,
            response_format=rf,
            max_tokens=max_tokens,
        )

        # Strip Qwen3 thinking blocks if present
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        raw = re.sub(r"^```(?:json)?\s*\n(.*?)\n```\s*$", r"\1", raw, flags=re.DOTALL).strip()

        # If empty after stripping, raise a clear error (triggers retry in caller)
        if not raw:
            raise AgentError("LLM returned empty response after stripping think tags")

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AgentError(f"Invalid JSON from LLM: {exc}\nRaw response: {raw[:200]}")
        if schema and "required" in schema:
            missing = [k for k in schema["required"] if k not in result]
            if missing:
                raise AgentError(f"LLM JSON missing required keys: {missing}")
        return result

    async def close(self) -> None:
        await self._client.aclose()