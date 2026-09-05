from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from backend.ai.agent_roles import AgentRole, get_agent_prompt
from backend.ai.cache import response_cache
from backend.ai.models import AgentOutput
from backend.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 2.0
MAX_DELAY = 30.0


class KeyPool:
    def __init__(self) -> None:
        self._keys: list[str] = []
        self._last_used: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._min_interval = 3.0

    def load(self) -> None:
        seen = set()
        for i in range(1, 6):
            key = getattr(settings, f"groq_agent_{i}_api_key", "")
            if key and key not in seen:
                self._keys.append(key)
                self._last_used[key] = 0.0
                seen.add(key)
        if settings.ai_api_key and settings.ai_api_key not in seen:
            self._keys.append(settings.ai_api_key)
            self._last_used[settings.ai_api_key] = 0.0
        logger.info(f"Key pool loaded: {len(self._keys)} keys")

    async def acquire(self) -> str | None:
        async with self._lock:
            now = time.monotonic()
            best_key = None
            best_wait = float("inf")
            for key in self._keys:
                elapsed = now - self._last_used[key]
                wait = max(0.0, self._min_interval - elapsed)
                if wait < best_wait:
                    best_wait = wait
                    best_key = key
            if best_key and best_wait > 0:
                self._lock.release()
                await asyncio.sleep(best_wait)
                await self._lock.acquire()
            if best_key:
                self._last_used[best_key] = time.monotonic()
            return best_key

    def mark_used(self, key: str) -> None:
        self._last_used[key] = time.monotonic()

    @property
    def count(self) -> int:
        return len(self._keys)


key_pool = KeyPool()


class GroqAgentProvider:
    def __init__(self, agent_role: AgentRole, agent_number: int) -> None:
        self.role = agent_role
        self.agent_number = agent_number
        cfg = settings.get_agent_config(agent_number)
        self._fallback_key = cfg["api_key"]
        self.model = cfg["model"]
        self.base_url = cfg["base_url"].rstrip("/")
        self.system_prompt = get_agent_prompt(agent_role)

    async def chat(self, user_message: str, context_summary: str = "") -> AgentOutput:
        start = time.monotonic()
        messages = self._build_messages(user_message, context_summary)

        cached = response_cache.get(self.role.value, messages, self.model)
        if cached:
            logger.debug("Cache hit for %s", self.role.value)
            return AgentOutput(
                agent=self.role, raw_response=cached.get("raw", ""),
                parsed=cached.get("parsed", {}), success=True,
                confidence=cached.get("confidence", 0.7),
                tokens_used=cached.get("tokens", 0),
                duration_ms=(time.monotonic() - start) * 1000,
            )

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                key = await key_pool.acquire() or self._fallback_key

                result = await self._send_request(messages, key)
                key_pool.mark_used(key)

                if result.success:
                    response_cache.set(self.role.value, messages, {
                        "raw": result.raw_response,
                        "parsed": result.parsed,
                        "confidence": result.confidence,
                        "tokens": result.tokens_used,
                    }, self.model)
                    result.duration_ms = (time.monotonic() - start) * 1000
                    return result

                last_error = result.error
                if result.error and "Rate limited" in result.error:
                    logger.warning(
                        f"Agent {self.role.value} rate limited on key...{key[-6:]}, "
                        f"retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                result.duration_ms = (time.monotonic() - start) * 1000
                return result

            except Exception as e:
                last_error = str(e)
                logger.error(f"Agent {self.role.value} attempt {attempt + 1} error: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(BASE_DELAY * (2 ** attempt), MAX_DELAY))

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

    async def _send_request(self, messages: list[dict], api_key: str) -> AgentOutput:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
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
                    return AgentOutput(
                        agent=self.role, success=False,
                        error="Rate limited",
                        duration_ms=(time.monotonic() - start) * 1000,
                    )

                if resp.status_code == 503:
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
                if not isinstance(parsed, dict):
                    parsed = {"solution": str(parsed), "confidence": 0.6}
                confidence = parsed.get("confidence", 0.7)

                return AgentOutput(
                    agent=self.role, raw_response=content, parsed=parsed,
                    confidence=float(confidence), success=True,
                    tokens_used=usage.get("total_tokens", 0),
                    duration_ms=(time.monotonic() - start) * 1000,
                )
        except httpx.TimeoutException:
            return AgentOutput(
                agent=self.role, success=False, error="Timeout",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except httpx.ConnectError as e:
            return AgentOutput(
                agent=self.role, success=False, error=f"Connection error: {e}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
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
