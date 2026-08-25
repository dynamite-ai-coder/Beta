from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from backend.config import settings
from backend.models.schemas import TaskState
from backend.tasks.repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._events: dict[str, list[dict]] = {}
        self._pending_results: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def _get_repo(self) -> TaskRepository | None:
        try:
            from backend.database import async_session
            session = async_session()
            return TaskRepository(session)
        except Exception as e:
            logger.error("Failed to create DB session: %s", e)
            return None

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
            "assigned_client": None,
        }
        async with self._lock:
            self._tasks[task_id] = task
            self._events[task_id] = []

        repo = await self._get_repo()
        if repo:
            try:
                await repo.create_task(
                    task_id=task_id,
                    target_url=target_url,
                    username=username,
                    password=password,
                    instruction=instruction,
                )
                await repo.add_event(task_id, "created")
            except Exception as e:
                logger.error("Failed to persist task to DB: %s", e)

        return task

    def get_task(self, task_id: str) -> dict | None:
        task = self._tasks.get(task_id)
        if task:
            return {k: v for k, v in task.items() if k != "password"}
        return None

    def _get_task_internal(self, task_id: str) -> dict | None:
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
                self._tasks[task_id]["updated_at"] = datetime.now(timezone.utc)
                if reason:
                    self._tasks[task_id]["reason"] = reason
                self._add_event(task_id, "state_change", state.value)

        repo = await self._get_repo()
        if repo:
            try:
                await repo.update_task_state(
                    task_id, state.value, reason=reason
                )
                await repo.add_event(task_id, "state_change", state.value)
            except Exception as e:
                logger.error("Failed to persist state change to DB: %s", e)

    def _add_event(self, task_id: str, event: str, data: str | None = None) -> None:
        if task_id in self._events:
            self._events[task_id].append({
                "event": event,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    async def execute_task(self, task_id: str) -> None:
        task = self._get_task_internal(task_id)
        if not task:
            return

        from backend.services.client_manager import client_manager
        from backend.services.ws_protocol import msg_task_assigned

        client_id = client_manager.get_ready_client()
        if not client_id:
            await self.update_task_state(
                task_id, TaskState.FAILURE, "No browser client available"
            )
            self._add_event(task_id, "no_client")
            return

        assigned = await client_manager.assign_task(client_id, task_id)
        if not assigned:
            await self.update_task_state(
                task_id, TaskState.FAILURE, "Failed to assign client"
            )
            return

        task["assigned_client"] = client_id
        await self.update_task_state(task_id, TaskState.STARTING)
        self._add_event(task_id, "assigned_to_client", client_id)

        actions = [
            {"action": "navigate", "url": task["target_url"]},
            {"action": "type", "selector": "username", "value": task["username"]},
            {"action": "type", "selector": "password", "value": task["password"]},
            {"action": "click", "selector": "submit"},
        ]

        assign_msg = msg_task_assigned(
            task_id=task_id,
            actions=actions,
            target_url=task["target_url"],
            instruction=task["instruction"],
        )

        sent = await client_manager.send_to_client(client_id, assign_msg)
        if not sent:
            await self.update_task_state(
                task_id, TaskState.FAILURE, "Failed to send task to client"
            )
            await client_manager.release_task(client_id, task_id)
            return

        await self.update_task_state(task_id, TaskState.RUNNING)

        try:
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            async with self._lock:
                self._pending_results[task_id] = future

            result = await asyncio.wait_for(future, timeout=settings.task_timeout)

            status = result.get("status", "success")
            if status == "success":
                final_state = TaskState.SUCCESS
            elif status == "captcha":
                final_state = TaskState.WAITING_FOR_MANUAL_ACTION
            else:
                final_state = TaskState.FAILURE

            await self.update_task_state(
                task_id, final_state, result.get("reason")
            )
            task["result"] = result.get("result")
            task["reason"] = result.get("reason")
            self._add_event(task_id, "task_completed", final_state.value)
            self.save_result(task_id)

        except asyncio.TimeoutError:
            await self.update_task_state(
                task_id, TaskState.TIMEOUT, "Task timed out"
            )
            cancel_msg = {"type": "TASK_CANCEL", "task_id": task_id}
            await client_manager.send_to_client(client_id, cancel_msg)
            self._add_event(task_id, "timeout")
        except Exception as e:
            logger.error("Task %s error: %s", task_id, e)
            await self.update_task_state(
                task_id, TaskState.FAILURE, str(e)
            )
        finally:
            async with self._lock:
                self._pending_results.pop(task_id, None)
            await client_manager.release_task(client_id, task_id)

    async def complete_task_from_client(
        self, task_id: str, status: str, result: dict
    ) -> None:
        future = self._pending_results.get(task_id)
        if future and not future.done():
            future.set_result({"status": status, **result})

    async def stop_task(self, task_id: str) -> bool:
        task = self._get_task_internal(task_id)
        if task and task.get("assigned_client"):
            from backend.services.client_manager import client_manager
            from backend.services.ws_protocol import msg_task_cancel
            client_id = task["assigned_client"]
            await client_manager.send_to_client(client_id, msg_task_cancel(task_id))
            await self.update_task_state(task_id, TaskState.STOPPED, "Stopped by user")
            self._add_event(task_id, "task_stopped")
            self.save_result(task_id)
            return True
        return False

    async def manual_action_continue(self, task_id: str) -> bool:
        task = self._get_task_internal(task_id)
        if task and task["state"] == TaskState.WAITING_FOR_MANUAL_ACTION:
            await self.update_task_state(
                task_id, TaskState.RUNNING, "Resumed after manual action"
            )
            self._add_event(task_id, "manual_action_resumed")
            return True
        return False

    async def cleanup_all(self) -> None:
        async with self._lock:
            self._pending_results.clear()

    def save_result(self, task_id: str) -> None:
        task = self._get_task_internal(task_id)
        if not task:
            return

        state = task["state"]
        state_val = state.value if isinstance(state, TaskState) else state
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
