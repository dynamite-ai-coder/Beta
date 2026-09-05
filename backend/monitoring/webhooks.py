from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    RATE_LIMIT = "rate_limit"
    AGENT_FAILURE = "agent_failure"
    WORKFLOW_TIMEOUT = "workflow_timeout"
    KEY Exhausted = "key_exhausted"
    HEALTH_CHANGE = "health_change"


@dataclass
class Webhook:
    id: str
    url: str
    events: list[str] = field(default_factory=list)
    enabled: bool = True
    secret: str = ""
    created_at: float = field(default_factory=time.time)
    last_triggered: float = 0.0
    fail_count: int = 0


class WebhookManager:
    def __init__(self):
        self._webhooks: dict[str, Webhook] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._processor_task: Optional[asyncio.Task] = None

    def register(self, url: str, events: list[str] = None, secret: str = "") -> Webhook:
        webhook_id = f"wh-{len(self._webhooks) + 1}"
        webhook = Webhook(
            id=webhook_id, url=url,
            events=events or [e.value for e in EventType],
            secret=secret,
        )
        self._webhooks[webhook_id] = webhook
        logger.info("Webhook registered: %s -> %s", webhook_id, url)
        return webhook

    def unregister(self, webhook_id: str) -> bool:
        if webhook_id in self._webhooks:
            del self._webhooks[webhook_id]
            return True
        return False

    async def emit(self, event: str, data: dict) -> None:
        for webhook in self._webhooks.values():
            if webhook.enabled and event in webhook.events:
                await self._queue.put((webhook, event, data))

    async def start(self) -> None:
        self._processor_task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        if self._processor_task:
            self._processor_task.cancel()

    async def _process_loop(self) -> None:
        while True:
            try:
                webhook, event, data = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
                await self._send(webhook, event, data)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Webhook processor error: %s", e)

    async def _send(self, webhook: Webhook, event: str, data: dict) -> None:
        payload = {
            "event": event,
            "data": data,
            "timestamp": time.time(),
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Content-Type": "application/json"}
                if webhook.secret:
                    import hashlib
                    import hmac
                    import json
                    body = json.dumps(payload)
                    sig = hmac.new(webhook.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
                    headers["X-Webhook-Secret"] = sig

                resp = await client.post(webhook.url, json=payload, headers=headers)
                if resp.status_code < 300:
                    webhook.last_triggered = time.time()
                    webhook.fail_count = 0
                    logger.debug("Webhook sent: %s -> %s", event, webhook.url)
                else:
                    webhook.fail_count += 1
                    logger.warning("Webhook failed: %s (status=%d)", webhook.url, resp.status_code)
        except Exception as e:
            webhook.fail_count += 1
            logger.warning("Webhook error: %s - %s", webhook.url, e)

    def list_all(self) -> list[dict]:
        return [{
            "id": w.id,
            "url": w.url,
            "events": w.events,
            "enabled": w.enabled,
            "last_triggered": w.last_triggered,
            "fail_count": w.fail_count,
        } for w in self._webhooks.values()]


webhook_manager = WebhookManager()
