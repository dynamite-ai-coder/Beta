from __future__ import annotations

import json
import logging
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


def msg_client_register(client_id: str, token: str) -> dict[str, Any]:
    return make_message("CLIENT_REGISTER", client_id=client_id, payload={"token": token})


def msg_client_registered(client_id: str) -> dict[str, Any]:
    return make_message("CLIENT_REGISTERED", client_id=client_id)


def msg_client_ready(client_id: str) -> dict[str, Any]:
    return make_message("CLIENT_READY", client_id=client_id)


def msg_browser_starting(client_id: str) -> dict[str, Any]:
    return make_message("BROWSER_STARTING", client_id=client_id)


def msg_browser_ready(client_id: str) -> dict[str, Any]:
    return make_message("BROWSER_READY", client_id=client_id)


def msg_browser_error(client_id: str, error: str) -> dict[str, Any]:
    return make_message("BROWSER_ERROR", client_id=client_id, payload={"error": error})


def msg_browser_restarting(client_id: str) -> dict[str, Any]:
    return make_message("BROWSER_RESTARTING", client_id=client_id)


def msg_browser_stopped(client_id: str) -> dict[str, Any]:
    return make_message("BROWSER_STOPPED", client_id=client_id)


def msg_task_assigned(task_id: str, actions: list[dict], target_url: str = "", instruction: str = "") -> dict[str, Any]:
    return make_message(
        "TASK_ASSIGNED", task_id=task_id,
        payload={"actions": actions, "target_url": target_url, "instruction": instruction},
    )


def msg_task_started(task_id: str) -> dict[str, Any]:
    return make_message("TASK_STARTED", task_id=task_id)


def msg_task_progress(task_id: str, progress: dict[str, Any]) -> dict[str, Any]:
    return make_message("TASK_PROGRESS", task_id=task_id, payload=progress)


def msg_task_result(task_id: str, status: str, result: dict[str, Any]) -> dict[str, Any]:
    return make_message("TASK_RESULT", task_id=task_id, payload={"status": status, "result": result})


def msg_task_error(task_id: str, error: str, error_code: str = "UNKNOWN") -> dict[str, Any]:
    return make_message("TASK_ERROR", task_id=task_id, payload={"error": error, "error_code": error_code})


def msg_task_timeout(task_id: str) -> dict[str, Any]:
    return make_message("TASK_TIMEOUT", task_id=task_id)


def msg_task_cancel(task_id: str) -> dict[str, Any]:
    return make_message("TASK_CANCEL", task_id=task_id)


def msg_heartbeat(direction: str = "client") -> dict[str, Any]:
    return make_message("CLIENT_HEARTBEAT" if direction == "client" else "SERVER_HEARTBEAT")


def msg_client_disconnected(client_id: str) -> dict[str, Any]:
    return make_message("CLIENT_DISCONNECTED", client_id=client_id)


def msg_client_reconnected(client_id: str) -> dict[str, Any]:
    return make_message("CLIENT_RECONNECTED", client_id=client_id)


def parse_message(data: str) -> dict[str, Any] | None:
    try:
        msg = json.loads(data)
        if "type" not in msg:
            return None
        return msg
    except (json.JSONDecodeError, TypeError):
        return None
