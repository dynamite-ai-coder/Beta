from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

import websockets

from client.config import ClientConfig
from client.ws_protocol import (
    msg_browser_error,
    msg_browser_ready,
    msg_browser_starting,
    msg_heartbeat,
    msg_ready,
    msg_register,
    msg_task_error,
    msg_task_progress,
    msg_task_result,
    msg_task_started,
    parse_message,
)

logger = logging.getLogger(__name__)


class WebSocketClient:
    def __init__(
        self,
        config: ClientConfig,
        on_task: Callable[[dict], Any],
    ) -> None:
        self.config = config
        self._on_task = on_task
        self._ws = None
        self._connected = False
        self._running = False
        self._reconnect_delay = config.reconnect_delay_start
        self._browser_manager = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect_loop()
            except Exception as e:
                logger.error(f"Connection error: {e}")
            if self._running:
                logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self.config.reconnect_delay_max,
                )

    async def _connect_loop(self) -> None:
        url = f"{self.config.ws_url}/api/clients/ws/agent"
        logger.info(f"Connecting to {url}")

        async with websockets.connect(url) as ws:
            self._ws = ws
            reg = msg_register(self.config.client_id, self.config.client_token)
            await ws.send(json.dumps(reg))

            raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
            resp = parse_message(raw)
            if not resp or resp.get("type") != "CLIENT_REGISTERED":
                logger.error("Registration failed")
                return

            self._connected = True
            self._reconnect_delay = self.config.reconnect_delay_start
            logger.info(f"Registered as {self.config.client_id}")

            await ws.send(json.dumps(msg_ready(self.config.client_id)))

            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            try:
                async for message in ws:
                    msg = parse_message(message)
                    if not msg:
                        continue
                    await self._handle_message(msg)
            finally:
                heartbeat_task.cancel()
                self._connected = False

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type", "")

        if msg_type == "TASK_ASSIGNED":
            task_id = msg.get("task_id", "")
            logger.info(f"Task assigned: {task_id}")
            asyncio.create_task(self._execute_task(msg))

        elif msg_type == "TASK_CANCEL":
            task_id = msg.get("task_id", "")
            logger.info(f"Task cancelled: {task_id}")

        elif msg_type == "SERVER_HEARTBEAT":
            pass

        elif msg_type == "BROWSER_RESTARTING":
            logger.info("Server requested browser restart")

    async def _execute_task(self, msg: dict[str, Any]) -> None:
        task_id = msg.get("task_id", "")
        payload = msg.get("payload", {})
        actions = payload.get("actions", [])
        target_url = payload.get("target_url", "")

        try:
            await self._send(msg_task_started(task_id))

            from client.browser import create_browser_manager
            if not self._browser_manager:
                self._browser_manager = create_browser_manager(max_workers=1)
            manager = self._browser_manager
            worker = await manager.get_or_create_worker()

            if not worker.is_ready:
                await self._send(msg_browser_starting(self.config.client_id))
                started = await worker.start()
                if not started:
                    await self._send(msg_browser_error(self.config.client_id, "Failed to start browser"))
                    await self._send(msg_task_error(task_id, "Browser start failed"))
                    return
                await self._send(msg_browser_ready(self.config.client_id))

            step = 0
            for action in actions:
                step += 1
                action_type = action.get("action", "")
                await self._send(msg_task_progress(task_id, step, f"Executing {action_type}"))

                if action_type == "navigate":
                    url = action.get("url", "")
                    if url:
                        await worker.navigate(url)

                elif action_type == "type":
                    selector = action.get("selector", "")
                    value = action.get("value", "")
                    if selector and value:
                        await worker.type_text(selector, value)

                elif action_type == "click":
                    selector = action.get("selector", "")
                    if selector:
                        await worker.click_element(selector)

                elif action_type == "screenshot":
                    pass

            await asyncio.sleep(2)

            current_url = await worker.get_current_url()
            page_source = await worker.get_page_source()
            has_captcha = await worker.detect_captcha()

            result = {
                "current_url": current_url,
                "page_title": "",
                "has_captcha": has_captcha,
                "steps_completed": step,
            }

            if has_captcha:
                await self._send(msg_task_result(task_id, "captcha", result))
            else:
                await self._send(msg_task_result(task_id, "success", result))

        except Exception as e:
            logger.error(f"Task execution error: {e}")
            await self._send(msg_task_error(task_id, str(e)))

    async def _heartbeat_loop(self) -> None:
        while self._connected:
            try:
                if self._ws:
                    await self._ws.send(json.dumps(msg_heartbeat()))
                await asyncio.sleep(self.config.heartbeat_interval)
            except Exception:
                break

    async def _send(self, msg: dict[str, Any]) -> None:
        if self._ws:
            try:
                await self._ws.send(json.dumps(msg))
            except Exception as e:
                logger.error(f"Send error: {e}")

    async def disconnect(self) -> None:
        self._running = False
        if self._browser_manager:
            await self._browser_manager.stop_all()
            self._browser_manager = None
        if self._ws:
            await self._ws.close()
