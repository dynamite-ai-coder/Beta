from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchTask:
    id: str
    payload: dict
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    result: Any = None
    error: str = ""
    retries: int = 0
    priority: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "latency_ms": round((self.completed_at - self.started_at) * 1000, 1) if self.completed_at else 0,
            "retries": self.retries,
            "error": self.error,
        }


class BatchQueue:
    def __init__(self, max_concurrent: int = 3, max_queue: int = 100):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue)
        self._tasks: dict[str, BatchTask] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = 0
        self._processor_task: Optional[asyncio.Task] = None
        self._handler: Optional[Callable] = None
        self._stats = {
            "total": 0, "completed": 0, "failed": 0,
            "avg_latency_ms": 0, "queue_size": 0,
        }

    def set_handler(self, handler: Callable) -> None:
        self._handler = handler

    async def add(self, payload: dict, priority: int = 0) -> str:
        task_id = f"batch-{uuid.uuid4().hex[:8]}"
        task = BatchTask(id=task_id, payload=payload, priority=priority)
        self._tasks[task_id] = task
        self._stats["total"] += 1
        await self._queue.put((-priority, time.time(), task_id))
        self._stats["queue_size"] = self._queue.qsize()
        logger.info("Batch task added: %s (priority=%d, queue=%d)", task_id, priority, self._queue.qsize())
        return task_id

    async def start(self, handler: Callable) -> None:
        self._handler = handler
        self._processor_task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

    async def _process_loop(self) -> None:
        while True:
            try:
                _, _, task_id = await self._queue.get()
                task = self._tasks.get(task_id)
                if not task or task.status == TaskStatus.CANCELLED:
                    continue

                async with self._semaphore:
                    await self._execute_task(task)
                self._stats["queue_size"] = self._queue.qsize()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Batch processor error: %s", e)
                await asyncio.sleep(1)

    async def _execute_task(self, task: BatchTask) -> None:
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self._running += 1

        try:
            if self._handler:
                task.result = await self._handler(task.payload)
            else:
                task.result = {"status": "no_handler"}
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            self._stats["completed"] += 1
            latency = (task.completed_at - task.started_at) * 1000
            n = self._stats["completed"]
            self._stats["avg_latency_ms"] = (
                (self._stats["avg_latency_ms"] * (n - 1) + latency) / n
            )
            logger.info("Batch task completed: %s (%.0fms)", task.id, latency)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = time.time()
            self._stats["failed"] += 1
            logger.error("Batch task failed: %s - %s", task.id, e)
        finally:
            self._running -= 1

    def get_task(self, task_id: str) -> Optional[BatchTask]:
        return self._tasks.get(task_id)

    def get_status(self, task_id: str) -> Optional[dict]:
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            return True
        return False

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "running": self._running,
            "queue_size": self._queue.qsize(),
        }


batch_queue = BatchQueue()
