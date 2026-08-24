from __future__ import annotations

import json
import logging

import httpx

from backend.config import settings
from backend.models.schemas import AISelectors

logger = logging.getLogger(__name__)


class AIProvider:
    def __init__(self) -> None:
        self._api_key = settings.groq_api_key
        self._model = settings.groq_model
        self._base_url = "https://api.groq.com/openai/v1"

    async def parse_selectors(self, prompt: str) -> AISelectors | None:
        if not self._api_key:
            logger.warning("No GROQ_API_KEY configured, returning None")
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": "You are a web element identification expert. Respond only with valid JSON."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 1024,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_json_response(content)
        except Exception as e:
            logger.error("AI provider error: %s", e)
            return None

    def _parse_json_response(self, content: str) -> AISelectors | None:
        try:
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            data = json.loads(content)
            return AISelectors(**data)
        except (json.JSONDecodeError, KeyError, Exception) as e:
            logger.error("Failed to parse AI response: %s", e)
            return None

    async def chat(self, system_prompt: str, user_prompt: str) -> str | None:
        if not self._api_key:
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1024,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("AI chat error: %s", e)
            return None
