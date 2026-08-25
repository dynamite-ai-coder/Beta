from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from backend.ai.agent_roles import AgentRole, AGENT_SYSTEM_PROMPTS
from backend.ai.models import AgentOutput
from backend.config import settings

logger = logging.getLogger(__name__)


class GroqAgentProvider:
    def __init__(self, agent_role: AgentRole, agent_number: int) -> None:
        self.role = agent_role
        self.agent_number = agent_number
        cfg = settings.get_agent_config(agent_number)
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.base_url = cfg["base_url"].rstrip("/")
        self.system_prompt = AGENT_SYSTEM_PROMPTS.get(agent_role, "")

    async def chat(self, user_message: str, context_summary: str = "") -> AgentOutput:
        start = time.monotonic()
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if context_summary:
            messages.append({"role": "system", "content": f"Current context:\n{context_summary}"})
        messages.append({"role": "user", "content": user_message})

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
                    logger.warning(f"Agent {self.role.value} rate limited")
                    return AgentOutput(
                        agent=self.role, success=False,
                        error="Rate limited", duration_ms=(time.monotonic() - start) * 1000,
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
            logger.error(f"Agent {self.role.value} timeout")
            return AgentOutput(
                agent=self.role, success=False, error="Timeout",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            logger.error(f"Agent {self.role.value} error: {e}")
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
