from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import EventRow, TaskRow

logger = logging.getLogger(__name__)


class TaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_task(
        self,
        task_id: str,
        target_url: str,
        username: str,
        password: str,
        instruction: str,
    ) -> TaskRow:
        now = datetime.now(timezone.utc)
        task = TaskRow(
            task_id=task_id,
            state="QUEUED",
            target_url=target_url,
            username=username,
            password=password,
            instruction=instruction,
            created_at=now,
            updated_at=now,
        )
        self._db.add(task)
        await self._db.flush()
        return task

    async def get_task(self, task_id: str) -> TaskRow | None:
        result = await self._db.execute(
            select(TaskRow).where(TaskRow.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def update_task_state(
        self,
        task_id: str,
        state: str,
        reason: str | None = None,
        result: str | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        task = await self.get_task(task_id)
        if not task:
            return
        task.state = state
        task.updated_at = datetime.now(timezone.utc)
        if reason:
            task.reason = reason
        if result:
            task.result = result
        if screenshot_path:
            task.screenshot_path = screenshot_path
        if state in ("SUCCESS", "FAILURE", "STOPPED", "TIMEOUT"):
            task.completed_at = datetime.now(timezone.utc)
        await self._db.flush()

    async def add_event(
        self,
        task_id: str,
        event: str,
        data: str | None = None,
    ) -> None:
        event_row = EventRow(
            task_id=task_id,
            event=event,
            data=data,
            timestamp=datetime.now(timezone.utc),
        )
        self._db.add(event_row)
        await self._db.flush()

    async def get_events(self, task_id: str) -> list[dict]:
        result = await self._db.execute(
            select(EventRow)
            .where(EventRow.task_id == task_id)
            .order_by(EventRow.timestamp)
        )
        return [row.to_dict() for row in result.scalars().all()]

    async def list_tasks(
        self,
        limit: int = 50,
        offset: int = 0,
        state: str | None = None,
    ) -> list[TaskRow]:
        query = select(TaskRow).order_by(
            TaskRow.created_at.desc()
        )
        if state:
            query = query.where(TaskRow.state == state)
        query = query.limit(limit).offset(offset)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def delete_task(self, task_id: str) -> bool:
        task = await self.get_task(task_id)
        if task:
            await self._db.delete(task)
            await self._db.flush()
            return True
        return False

    async def cleanup_old_tasks(self, days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._db.execute(
            delete(TaskRow).where(TaskRow.created_at < cutoff)
        )
        await self._db.flush()
        return result.rowcount
