from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from croniter import croniter

logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(self) -> None:
        self._scheduled_tasks: dict[str, dict] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def add_scheduled_task(
        self,
        name: str,
        target_url: str,
        username: str,
        password: str,
        instruction: str,
        cron_expression: str,
    ) -> dict:
        if not croniter.is_valid(cron_expression):
            raise ValueError(f"Invalid cron expression: {cron_expression}")

        task_id = str(uuid.uuid4())
        cron = croniter(cron_expression, datetime.now(timezone.utc))
        next_run = cron.get_next(datetime)

        scheduled_task = {
            "id": task_id,
            "name": name,
            "target_url": target_url,
            "username": username,
            "password": password,
            "instruction": instruction,
            "cron_expression": cron_expression,
            "enabled": True,
            "last_run": None,
            "next_run": next_run,
            "created_at": datetime.now(timezone.utc),
        }
        self._scheduled_tasks[task_id] = scheduled_task
        logger.info("Scheduled task added: %s (next run: %s)", name, next_run)
        return scheduled_task

    def remove_scheduled_task(self, task_id: str) -> bool:
        if task_id in self._scheduled_tasks:
            del self._scheduled_tasks[task_id]
            logger.info("Scheduled task removed: %s", task_id)
            return True
        return False

    def enable_scheduled_task(self, task_id: str) -> bool:
        task = self._scheduled_tasks.get(task_id)
        if task:
            task["enabled"] = True
            return True
        return False

    def disable_scheduled_task(self, task_id: str) -> bool:
        task = self._scheduled_tasks.get(task_id)
        if task:
            task["enabled"] = False
            return True
        return False

    def get_scheduled_task(self, task_id: str) -> dict | None:
        return self._scheduled_tasks.get(task_id)

    def list_scheduled_tasks(self) -> list[dict]:
        return list(self._scheduled_tasks.values())

    async def start(self, task_manager) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(task_manager))
        logger.info("Task scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Task scheduler stopped")

    async def _run_loop(self, task_manager) -> None:
        while self._running:
            now = datetime.now(timezone.utc)
            for task_id, scheduled in list(self._scheduled_tasks.items()):
                if not scheduled["enabled"]:
                    continue
                if scheduled["next_run"] and scheduled["next_run"] <= now:
                    await self._execute_scheduled_task(task_manager, scheduled)
            await asyncio.sleep(10)

    async def _execute_scheduled_task(
        self, task_manager, scheduled: dict
    ) -> None:
        try:
            logger.info(
                "Executing scheduled task: %s", scheduled["name"]
            )
            task_id = str(uuid.uuid4())
            await task_manager.create_task(
                task_id=task_id,
                target_url=scheduled["target_url"],
                username=scheduled["username"],
                password=scheduled["password"],
                instruction=scheduled["instruction"],
            )
            asyncio.create_task(
                task_manager.execute_task(task_id)
            )

            scheduled["last_run"] = datetime.now(timezone.utc)
            cron = croniter(
                scheduled["cron_expression"],
                datetime.now(timezone.utc),
            )
            scheduled["next_run"] = cron.get_next(datetime)
            logger.info(
                "Scheduled task %s executed, next run: %s",
                scheduled["name"],
                scheduled["next_run"],
            )
        except Exception as e:
            logger.error(
                "Error executing scheduled task %s: %s",
                scheduled["name"],
                e,
            )


scheduler = TaskScheduler()
