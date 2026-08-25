from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from selenium.common.exceptions import TimeoutException, WebDriverException

from backend.ai.identifier import ElementIdentifier
from backend.ai.provider import get_ai_provider
from backend.browser.agent import BrowserAgent
from backend.config import settings
from backend.models.schemas import TaskState

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._agents: dict[str, BrowserAgent] = {}
        self._events: dict[str, list[dict]] = {}
        self._ai_provider = get_ai_provider()
        self._ai_identifier = ElementIdentifier(self._ai_provider)
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        task_id: str,
        target_url: str,
        username: str,
        password: str,
        instruction: str,
    ) -> dict:
        now = datetime.now(timezone.utc)
        task = {
            "task_id": task_id,
            "state": TaskState.QUEUED,
            "target_url": target_url,
            "username": username,
            "password": password,
            "instruction": instruction,
            "created_at": now,
            "updated_at": now,
            "result": None,
            "reason": None,
            "screenshot_path": None,
            "preview_token": None,
        }
        async with self._lock:
            self._tasks[task_id] = task
            self._events[task_id] = []
        return task

    def get_task(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def get_events(self, task_id: str) -> list[dict]:
        return self._events.get(task_id, [])

    async def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        reason: str | None = None,
    ) -> None:
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["state"] = state
                self._tasks[task_id]["updated_at"] = (
                    datetime.now(timezone.utc)
                )
                if reason:
                    self._tasks[task_id]["reason"] = reason
                self._add_event(
                    task_id, "state_change", state.value
                )

    def _add_event(
        self,
        task_id: str,
        event: str,
        data: str | None = None,
    ) -> None:
        if task_id in self._events:
            self._events[task_id].append({
                "event": event,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    async def execute_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return

        agent = BrowserAgent(task_id, self._ai_identifier)
        self._agents[task_id] = agent

        try:
            await self.update_task_state(task_id, TaskState.STARTING)
            await asyncio.to_thread(agent.start_browser)
            self._add_event(task_id, "browser_started")

            await self.update_task_state(task_id, TaskState.RUNNING)
            self._add_event(task_id, "navigation_started")

            result = await agent.execute_login(
                task["target_url"],
                task["username"],
                task["password"],
                task["instruction"],
            )

            final_state = result.get("state", TaskState.FAILURE)
            await self.update_task_state(
                task_id, final_state, result.get("reason")
            )

            task["result"] = result.get("result")
            task["reason"] = result.get("reason")

            if final_state == TaskState.SUCCESS:
                screenshot = await asyncio.to_thread(agent.take_screenshot)
                if screenshot:
                    path = self._save_screenshot(
                        task_id, task["username"], screenshot
                    )
                    task["screenshot_path"] = path
                    self._add_event(
                        task_id, "screenshot_saved", path
                    )

            self._add_event(
                task_id, "task_completed", final_state.value
            )
            self.save_result(task_id)

        except (
            OSError, WebDriverException,
            TimeoutException, ValueError,
            RuntimeError, Exception,
        ) as e:
            logger.error(
                "Task %s execution error: %s [%s]",
                task_id, e, type(e).__name__,
            )
            await self.update_task_state(
                task_id, TaskState.FAILURE, f"{type(e).__name__}: {e}"
            )
        finally:
            await asyncio.to_thread(agent.close_browser)
            async with self._lock:
                self._agents.pop(task_id, None)

    def _save_screenshot(
        self, task_id: str, username: str, data: bytes
    ) -> str:
        os.makedirs(settings.img_dir, exist_ok=True)
        from backend.security.auth import sanitize_filename
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = sanitize_filename(username)
        filename = f"{ts}_{safe_name}_{task_id[:8]}.png"
        path = os.path.join(settings.img_dir, filename)
        with open(path, "wb") as f:
            f.write(data)
        return path

    async def stop_task(self, task_id: str) -> bool:
        agent = self._agents.get(task_id)
        if agent:
            await asyncio.to_thread(agent.close_browser)
            await self.update_task_state(
                task_id, TaskState.STOPPED, "Stopped by user"
            )
            self._add_event(task_id, "task_stopped")
            self.save_result(task_id)
            return True
        return False

    async def manual_action_continue(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task["state"] == TaskState.WAITING_FOR_MANUAL_ACTION:
            await self.update_task_state(
                task_id,
                TaskState.RUNNING,
                "Resumed after manual action",
            )
            self._add_event(task_id, "manual_action_resumed")
            return True
        return False

    async def cleanup_all(self) -> None:
        for task_id in list(self._agents.keys()):
            agent = self._agents.get(task_id)
            if agent:
                await asyncio.to_thread(agent.close_browser)
        async with self._lock:
            self._agents.clear()

    def save_result(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return

        state = task["state"]
        state_val = (
            state.value if isinstance(state, TaskState) else state
        )
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_url": task["target_url"],
            "username": task["username"],
            "task_id": task_id,
            "state": state_val,
            "reason": task.get("reason"),
            "screenshot_path": task.get("screenshot_path"),
        }
        with open(settings.results_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
