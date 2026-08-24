from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, task_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            if task_id not in self._connections:
                self._connections[task_id] = []
            self._connections[task_id].append(websocket)
        logger.info("WebSocket connected for task %s", task_id)

    async def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        async with self._lock:
            if task_id in self._connections:
                self._connections[task_id] = [
                    ws for ws in self._connections[task_id] if ws != websocket
                ]
                if not self._connections[task_id]:
                    del self._connections[task_id]
        logger.info("WebSocket disconnected for task %s", task_id)

    async def broadcast(
        self,
        task_id: str,
        event: str,
        data: dict | None = None,
    ) -> None:
        message = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        async with self._lock:
            connections = self._connections.get(task_id, []).copy()

        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_text(json.dumps(message))
            except Exception:
                disconnected.append(websocket)

        if disconnected:
            async with self._lock:
                if task_id in self._connections:
                    self._connections[task_id] = [
                        ws for ws in self._connections[task_id]
                        if ws not in disconnected
                    ]

    def get_connection_count(self, task_id: str | None = None) -> int:
        if task_id:
            return len(self._connections.get(task_id, []))
        return sum(len(conns) for conns in self._connections.values())


ws_manager = ConnectionManager()
