from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from backend.ai.models import ClientInfo

logger = logging.getLogger(__name__)


class ClientManager:
    def __init__(self) -> None:
        self._clients: dict[str, ClientInfo] = {}
        self._connections: dict[str, Any] = {}
        self._task_queue: asyncio.Queue[str] = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def register_client(self, client_id: str, connection: Any) -> ClientInfo:
        async with self._lock:
            info = ClientInfo(
                client_id=client_id,
                status="online",
                last_seen=datetime.now(timezone.utc),
                browser_status="unknown",
                connection_id=client_id,
            )
            self._clients[client_id] = info
            self._connections[client_id] = connection
            logger.info(f"Client registered: {client_id}")
            return info

    async def unregister_client(self, client_id: str) -> None:
        async with self._lock:
            self._clients.pop(client_id, None)
            self._connections.pop(client_id, None)
            logger.info(f"Client unregistered: {client_id}")

    async def update_client_status(self, client_id: str, **kwargs: Any) -> None:
        async with self._lock:
            if client_id in self._clients:
                for k, v in kwargs.items():
                    if hasattr(self._clients[client_id], k):
                        setattr(self._clients[client_id], k, v)
                self._clients[client_id].last_seen = datetime.now(timezone.utc)

    def get_client(self, client_id: str) -> Optional[ClientInfo]:
        return self._clients.get(client_id)

    def get_all_clients(self) -> list[ClientInfo]:
        return list(self._clients.values())

    def get_ready_client(self) -> Optional[str]:
        for cid, info in self._clients.items():
            if info.status == "online" and info.browser_status == "ready" and info.current_task is None:
                return cid
        return None

    async def assign_task(self, client_id: str, task_id: str) -> bool:
        async with self._lock:
            if client_id in self._clients:
                client = self._clients[client_id]
                if client.current_task is None and client.browser_status == "ready":
                    client.current_task = task_id
                    return True
        return False

    async def release_task(self, client_id: str, task_id: str) -> None:
        async with self._lock:
            if client_id in self._clients:
                client = self._clients[client_id]
                if client.current_task == task_id:
                    client.current_task = None

    def get_connection(self, client_id: str) -> Optional[Any]:
        return self._connections.get(client_id)

    async def send_to_client(self, client_id: str, message: dict[str, Any]) -> bool:
        conn = self._connections.get(client_id)
        if conn:
            try:
                import json
                await conn.send_text(json.dumps(message))
                return True
            except Exception as e:
                logger.error(f"Failed to send to {client_id}: {e}")
        return False

    async def broadcast_to_all(self, message: dict[str, Any]) -> int:
        sent = 0
        for cid in list(self._connections.keys()):
            if await self.send_to_client(cid, message):
                sent += 1
        return sent


client_manager = ClientManager()
