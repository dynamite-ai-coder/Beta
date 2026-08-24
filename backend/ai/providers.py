from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import httpx

from backend.models.schemas import AISelectors

logger = logging.getLogger(__name__)

CHAT_COMPLETIONS_PROMPT = (
    "You are a web element identification expert. "
    "Respond only with valid JSON."
)


class BaseAIProvider(ABC):
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

    @abstractmethod
    async def chat(self, system_prompt: str, user_prompt: str) -> str | None:
        pass

    async def parse_selectors(self, prompt: str) -> AISelectors | None:
        if not self._api_key:
            logger.warning("No API key for %s", self.__class__.__name__)
            return None
        response = await self.chat(CHAT_COMPLETIONS_PROMPT, prompt)
        if not response:
            return None
        return self._parse_json_response(response)

    def _parse_json_response(self, content: str) -> AISelectors | None:
        try:
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            data = json.loads(content)
            return AISelectors(**data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error("Failed to parse AI response: %s", e)
            return None


class OpenAICompatibleProvider(BaseAIProvider):
    _endpoint = "/chat/completions"
    _extra_headers: dict[str, str] = {}

    async def chat(self, system_prompt: str, user_prompt: str) -> str | None:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
        }
        return await self._post(f"{self._base_url}{self._endpoint}", headers, payload)

    async def _post(self, url: str, headers: dict, payload: dict) -> str | None:
        timeout = 60.0 if "ollama" in self._base_url else 30.0
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                return self._extract_content(resp.json())
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError) as e:
            logger.error("%s error: %s", self.__class__.__name__, e)
            return None

    def _extract_content(self, data: dict) -> str | None:
        return data["choices"][0]["message"]["content"]


class GroqProvider(OpenAICompatibleProvider):
    pass


class OpenAIProvider(OpenAICompatibleProvider):
    pass


class AnthropicProvider(BaseAIProvider):
    async def chat(self, system_prompt: str, user_prompt: str) -> str | None:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._base_url}/messages",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError) as e:
            logger.error("Anthropic error: %s", e)
            return None


class OllamaProvider(OpenAICompatibleProvider):
    _endpoint = "/api/chat"

    def _extract_content(self, data: dict) -> str | None:
        return data["message"]["content"]


PROVIDER_MAP: dict[str, type[BaseAIProvider]] = {
    "groq": GroqProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}


def create_provider(
    provider_type: str,
    api_key: str,
    model: str,
    base_url: str,
) -> BaseAIProvider:
    cls = PROVIDER_MAP.get(provider_type.lower())
    if not cls:
        available = list(PROVIDER_MAP.keys())
        raise ValueError(f"Unknown provider: {provider_type}. Use: {available}")
    return cls(api_key=api_key, model=model, base_url=base_url)
