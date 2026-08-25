from __future__ import annotations

import json
import logging

import httpx

from client.config import ClientConfig
from client.ui import print_error

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._headers = {}
        if config.api_token:
            self._headers["Authorization"] = (
                f"Bearer {config.api_token}"
            )

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.api_url}/health"
            )
            resp.raise_for_status()
            return resp.json()

    async def create_task(
        self,
        target_url: str,
        username: str,
        password: str,
        instruction: str = "Log in with the provided credentials",
    ) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._config.api_url}/api/v1/task",
                headers=self._headers,
                json={
                    "target_url": target_url,
                    "username": username,
                    "password": password,
                    "natural_language_instruction": instruction,
                },
            )
            if resp.status_code == 422:
                try:
                    detail = resp.json()
                    error_msg = detail.get("detail", str(detail))
                    if isinstance(error_msg, list):
                        errors = [
                            f"  {e.get('loc', [])}: {e.get('msg', '')}"
                            for e in error_msg
                        ]
                        error_msg = "\n".join(errors)
                    raise ValueError(error_msg)
                except (json.JSONDecodeError, ValueError) as ve:
                    if isinstance(ve, ValueError):
                        raise
                    raise ValueError(resp.text)
            resp.raise_for_status()
            return resp.json()

    async def get_task(self, task_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.api_url}/api/v1/task/{task_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_events(self, task_id: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.api_url}/api/v1/task/{task_id}/events",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def stop_task(self, task_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._config.api_url}/api/v1/task/{task_id}/stop",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def manual_action(self, task_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._config.api_url}/api/v1/task/{task_id}/manual-action",
                headers=self._headers,
                json={"action": "continue"},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_tasks(
        self,
        limit: int = 50,
        offset: int = 0,
        state: str | None = None,
    ) -> list[dict]:
        params = {"limit": limit, "offset": offset}
        if state:
            params["state"] = state
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.api_url}/api/v1/tasks",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_scheduled_tasks(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.api_url}/api/v1/scheduled-tasks",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_scheduled_task(
        self,
        name: str,
        target_url: str,
        username: str,
        password: str,
        instruction: str,
        cron_expression: str,
    ) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._config.api_url}/api/v1/scheduled-task",
                headers=self._headers,
                json={
                    "name": name,
                    "target_url": target_url,
                    "username": username,
                    "password": password,
                    "instruction": instruction,
                    "cron_expression": cron_expression,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def delete_scheduled_task(self, task_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{self._config.api_url}/api/v1/scheduled-task/{task_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_metrics(self) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.api_url}/metrics",
            )
            resp.raise_for_status()
            return resp.text
