from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from client.config import ClientConfig

logger = logging.getLogger(__name__)


class ChatClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._history: list[dict[str, str]] = []
        self._max_history = 50

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    def add_user_message(self, content: str) -> None:
        self._history.append({"role": "user", "content": content})
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def add_assistant_message(self, content: str) -> None:
        self._history.append({"role": "assistant", "content": content})
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def clear_history(self) -> None:
        self._history.clear()

    async def send_message(
        self,
        message: str,
        file_context: str = "",
    ) -> str:
        self.add_user_message(message)

        messages = list(self._history)
        if file_context:
            messages.insert(-1, {
                "role": "system",
                "content": f"Attached file content:\n{file_context[:8000]}",
            })

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_token:
            headers["Authorization"] = f"Bearer {self._config.api_token}"

        payload = {
            "model": "beta-virtual-ai",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{self._config.backend_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                self.add_assistant_message(content)
                return content
        except httpx.TimeoutException:
            error = "Request timed out. Please try again."
            self.add_assistant_message(error)
            return error
        except httpx.ConnectError:
            error = "Cannot connect to backend. Is the server running?"
            self.add_assistant_message(error)
            return error
        except Exception as e:
            error = f"Error: {e}"
            logger.error(f"Chat error: {e}")
            self.add_assistant_message(error)
            return error
