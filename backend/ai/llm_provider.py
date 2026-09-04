from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from backend.ai.agent_roles import AgentRole, AGENT_SYSTEM_PROMPTS
from backend.ai.models import AgentOutput
from backend.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 2.0
MAX_DELAY = 60.0


class GroqAgentProvider:
    def __init__(self, agent_role: AgentRole, agent_number: int) -> None:
        self.role = agent_role
        self.agent_number = agent_number
        cfg = settings.get_agent_config(agent_number)
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.base_url = cfg["base_url"].rstrip("/")
        self.system_prompt = AGENT_SYSTEM_PROMPTS.get(agent_role, "")
        self._last_request_time = 0.0
        self._min_request_interval = 2.5

    async def chat(self, user_message: str, context_summary: str = "") -> AgentOutput:
        start = time.monotonic()
        messages = self._build_messages(user_message, context_summary)

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                elapsed = time.monotonic() - self._last_request_time
                if elapsed < self._min_request_interval:
                    await asyncio.sleep(self._min_request_interval - elapsed)

                result = await self._send_request(messages)
                self._last_request_time = time.monotonic()

                if result.success:
                    result.duration_ms = (time.monotonic() - start) * 1000
                    return result

                last_error = result.error
                if result.error and "Rate limited" in result.error:
                    logger.warning(
                        f"Agent {self.role.value} rate limited, "
                        f"retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                result.duration_ms = (time.monotonic() - start) * 1000
                return result

            except Exception as e:
                last_error = str(e)
                logger.error(
                    f"Agent {self.role.value} attempt {attempt + 1} error: {e}"
                )
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    await asyncio.sleep(delay)

        logger.error(f"Agent {self.role.value} failed after {MAX_RETRIES} attempts")
        return AgentOutput(
            agent=self.role, success=False,
            error=f"Failed after {MAX_RETRIES} attempts: {last_error}",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def _build_messages(self, user_message: str, context_summary: str = "") -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if context_summary:
            messages.append({"role": "system", "content": f"Current context:\n{context_summary}"})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _send_request(self, messages: list[dict]) -> AgentOutput:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.3,
                        "max_tokens": settings.max_agent_output_size,
                    },
                )

                if resp.status_code == 429:
                    retry_after = resp.headers.get("retry-after")
                    logger.warning(
                        f"Agent {self.role.value} rate limited "
                        f"(retry-after: {retry_after})"
                    )
                    return AgentOutput(
                        agent=self.role, success=False,
                        error="Rate limited",
                        duration_ms=(time.monotonic() - start) * 1000,
                    )

                if resp.status_code == 503:
                    logger.warning(f"Agent {self.role.value} service unavailable")
                    return AgentOutput(
                        agent=self.role, success=False,
                        error="Service unavailable",
                        duration_ms=(time.monotonic() - start) * 1000,
                    )

                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                parsed = self._parse_response(content)
                confidence = parsed.get("confidence", 0.7)

                return AgentOutput(
                    agent=self.role, raw_response=content, parsed=parsed,
                    confidence=float(confidence), success=True,
                    tokens_used=usage.get("total_tokens", 0),
                    duration_ms=(time.monotonic() - start) * 1000,
                )
        except httpx.TimeoutException:
            logger.error(f"Agent {self.role.value} request timeout")
            return AgentOutput(
                agent=self.role, success=False, error="Timeout",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except httpx.ConnectError as e:
            logger.error(f"Agent {self.role.value} connection error: {e}")
            return AgentOutput(
                agent=self.role, success=False, error=f"Connection error: {e}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            logger.error(f"Agent {self.role.value} unexpected error: {e}")
            return AgentOutput(
                agent=self.role, success=False, error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    def _parse_response(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"solution": content, "confidence": 0.6}
