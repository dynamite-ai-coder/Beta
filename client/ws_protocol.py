from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1


def make_message(msg_type: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "type": msg_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    msg.update(kwargs)
    return msg


def msg_register(client_id: str, token: str) -> dict[str, Any]:
    return make_message("CLIENT_REGISTER", client_id=client_id, payload={"token": token})


def msg_ready(client_id: str) -> dict[str, Any]:
    return make_message("CLIENT_READY", client_id=client_id)


def msg_browser_starting(client_id: str) -> dict[str, Any]:
    return make_message("BROWSER_STARTING", client_id=client_id)


def msg_browser_ready(client_id: str) -> dict[str, Any]:
    return make_message("BROWSER_READY", client_id=client_id)


def msg_browser_error(client_id: str, error: str) -> dict[str, Any]:
    return make_message("BROWSER_ERROR", client_id=client_id, payload={"error": error})


def msg_task_started(task_id: str) -> dict[str, Any]:
    return make_message("TASK_STARTED", task_id=task_id)


def msg_task_progress(task_id: str, step: int, detail: str = "") -> dict[str, Any]:
    return make_message("TASK_PROGRESS", task_id=task_id, payload={"step": step, "detail": detail})


def msg_task_result(task_id: str, status: str, result: dict[str, Any]) -> dict[str, Any]:
    return make_message("TASK_RESULT", task_id=task_id, payload={"status": status, "result": result})


def msg_task_error(task_id: str, error: str) -> dict[str, Any]:
    return make_message("TASK_ERROR", task_id=task_id, payload={"error": error})


def msg_heartbeat() -> dict[str, Any]:
    return make_message("CLIENT_HEARTBEAT")


def parse_message(data: str) -> dict[str, Any] | None:
    try:
        msg = json.loads(data)
        if "type" not in msg:
            return None
        return msg
    except (json.JSONDecodeError, TypeError):
        return None
