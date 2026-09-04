from __future__ import annotations

import logging
from typing import Optional

import httpx

from client.config import ClientConfig
from client.local_ai import preprocess_prompt_async, is_local_ai_available

logger = logging.getLogger(__name__)


class ChatClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._session_id: Optional[str] = None
        self._history: list[dict[str, str]] = []

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def add_user_message(self, content: str) -> None:
        self._history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self._history.append({"role": "assistant", "content": content})

    def clear_history(self) -> None:
        self._history.clear()
        self._session_id = None

    async def send_message(
        self,
        message: str,
        file_context: str = "",
    ) -> str:
        self.add_user_message(message)

        original, processed = await preprocess_prompt_async(message, file_context)

        send_message = original
        send_file_context = file_context
        if processed:
            send_message = f"[Preprocessed context from local AI]\n{processed}\n\n[Original user message]\n{original}"
            if file_context:
                send_file_context = ""

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_token:
            headers["Authorization"] = f"Bearer {self._config.api_token}"

        payload = {
            "message": send_message,
            "session_id": self._session_id or "",
            "file_context": send_file_context,
        }

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{self._config.backend_url}/v1/chat/send",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["response"]
                self._session_id = data.get("session_id", self._session_id)
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
