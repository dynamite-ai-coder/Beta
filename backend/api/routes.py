from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.config import is_url_allowed, settings
from backend.models.schemas import (
    ManualActionRequest,
    TaskRequest,
    TaskResponse,
    TaskState,
)
from backend.security.auth import create_session_token, verify_api_key
from backend.streaming.preview import preview_streamer
from backend.streaming.websocket import ws_manager
from backend.tasks.scheduler import scheduler
from backend.ai.models import VirtualAIRequest
from backend.ai.orchestrator import orchestrator
from backend.services.client_manager import client_manager
from backend.services.ws_protocol import (
    parse_message, msg_client_registered, msg_client_ready,
    msg_browser_ready, msg_browser_error, msg_task_result,
    msg_task_error, msg_task_cancel, msg_heartbeat,
)
from backend.services.chat_history import chat_history

logger = logging.getLogger(__name__)
router = APIRouter()
ai_router = APIRouter()
client_router = APIRouter()

DEFAULT_INSTRUCTION = "Log in with the provided credentials"


def _get_task_manager(request: Request):
    return request.app.state.task_manager


def _parse_state(task: dict) -> TaskState:
    state = task["state"]
    return TaskState(state) if isinstance(state, str) else state


@router.post(
    "/task",
    response_model=TaskResponse,
    dependencies=[Depends(verify_api_key)],
)
async def create_task(
    request: Request, task_req: TaskRequest
) -> TaskResponse:
    client_ip = request.client.host if request.client else "unknown"
    tm = _get_task_manager(request)

    if not is_url_allowed(task_req.target_url):
        raise HTTPException(
            status_code=400,
            detail="Target URL is not allowed by policy",
        )

    task_id = str(uuid.uuid4())
    task = await tm.create_task(
        task_id=task_id,
        target_url=task_req.target_url,
        username=task_req.username,
        password=task_req.password,
        instruction=task_req.natural_language_instruction,
    )

    preview_token = create_session_token()
    task["preview_token"] = preview_token
    asyncio.create_task(tm.execute_task(task_id))

    logger.info("Task created: %s from %s", task_id, client_ip)

    return TaskResponse(
        task_id=task_id,
        state=TaskState.QUEUED,
        target_url=task_req.target_url,
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        preview_url=f"/task/{task_id}/preview?token={preview_token}",
    )


@router.get(
    "/task/{task_id}",
    response_model=TaskResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_task(request: Request, task_id: str) -> TaskResponse:
    tm = _get_task_manager(request)
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        task_id=task_id,
        state=_parse_state(task),
        target_url=task["target_url"],
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        result=task.get("result"),
        reason=task.get("reason"),
    )


@router.get(
    "/task/{task_id}/events",
    dependencies=[Depends(verify_api_key)],
)
async def get_task_events(
    request: Request, task_id: str
) -> list[dict]:
    tm = _get_task_manager(request)
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return tm.get_events(task_id)


@router.get(
    "/task/{task_id}/preview",
    dependencies=[Depends(verify_api_key)],
)
async def get_task_preview(
    request: Request, task_id: str, token: str
) -> StreamingResponse:
    tm = _get_task_manager(request)
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.get("preview_token") != token:
        raise HTTPException(status_code=403, detail="Invalid token")

    await preview_streamer.start_stream(task_id, token)
    return StreamingResponse(
        preview_streamer.generate_mjpeg(task_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post(
    "/task/{task_id}/manual-action",
    dependencies=[Depends(verify_api_key)],
)
async def manual_action(
    request: Request, task_id: str, req: ManualActionRequest
) -> dict:
    tm = _get_task_manager(request)
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if _parse_state(task) != TaskState.WAITING_FOR_MANUAL_ACTION:
        raise HTTPException(
            status_code=400,
            detail="Task is not waiting for manual action",
        )

    continued = await tm.manual_action_continue(task_id)
    if not continued:
        raise HTTPException(
            status_code=500, detail="Failed to resume task"
        )

    return {"status": "resumed", "task_id": task_id}


@router.post(
    "/task/{task_id}/stop",
    dependencies=[Depends(verify_api_key)],
)
async def stop_task(request: Request, task_id: str) -> dict:
    tm = _get_task_manager(request)
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    stopped = await tm.stop_task(task_id)
    if not stopped:
        raise HTTPException(
            status_code=400, detail="Could not stop task"
        )

    return {"status": "stopped", "task_id": task_id}


@router.get(
    "/tasks",
    dependencies=[Depends(verify_api_key)],
)
async def list_tasks(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    state: str | None = None,
) -> list[dict]:
    tm = _get_task_manager(request)
    tasks = []
    items = list(tm._tasks.items())[offset : offset + limit]
    for task_id, task in items:
        task_state = task["state"].value
        if state and task_state != state:
            continue
        tasks.append({
            "task_id": task_id,
            "state": task_state,
            "target_url": task["target_url"],
            "created_at": task["created_at"].isoformat(),
            "updated_at": task["updated_at"].isoformat(),
        })
    return tasks


def _validate_ws_auth(websocket: WebSocket) -> bool:
    from backend.config import settings
    if not settings.api_auth_token:
        return True
    auth = websocket.query_params.get("auth")
    if not auth:
        return False
    import secrets
    return secrets.compare_digest(
        auth, settings.api_auth_token
    )


@router.websocket("/ws/task/{task_id}")
async def websocket_task_updates(
    websocket: WebSocket, task_id: str
) -> None:
    if not _validate_ws_auth(websocket):
        await websocket.close(code=4003, reason="Unauthorized")
        return

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    tm = websocket.app.state.task_manager
    task = tm.get_task(task_id)
    if not task:
        await websocket.close(code=4004, reason="Task not found")
        return

    if task.get("preview_token") != token:
        await websocket.close(code=4003, reason="Invalid token")
        return

    await ws_manager.connect(websocket, task_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                msg = json.dumps({"event": "pong"})
                await websocket.send_text(msg)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, task_id)


@router.websocket("/ws/tasks")
async def websocket_all_tasks(websocket: WebSocket) -> None:
    if not _validate_ws_auth(websocket):
        await websocket.close(code=4003, reason="Unauthorized")
        return

    await websocket.accept()
    tm = websocket.app.state.task_manager

    try:
        while True:
            summary = [
                {
                    "task_id": tid,
                    "state": t["state"].value,
                    "updated_at": t["updated_at"].isoformat(),
                }
                for tid, t in tm._tasks.items()
            ]
            msg = json.dumps({"event": "tasks_update", "data": summary})
            await websocket.send_text(msg)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


class ScheduledTaskRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    target_url: str = Field(..., min_length=1, max_length=2048)
    username: str = Field(..., min_length=1, max_length=512)
    password: str = Field(..., min_length=1, max_length=1024)
    instruction: str = Field(
        default=DEFAULT_INSTRUCTION, max_length=4096
    )
    cron_expression: str = Field(..., min_length=1, max_length=64)


@router.post(
    "/scheduled-task",
    dependencies=[Depends(verify_api_key)],
)
async def create_scheduled_task(req: ScheduledTaskRequest) -> dict:
    try:
        task = scheduler.add_scheduled_task(
            name=req.name,
            target_url=req.target_url,
            username=req.username,
            password=req.password,
            instruction=req.instruction,
            cron_expression=req.cron_expression,
        )
        return {"status": "created", "task": task}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/scheduled-tasks",
    dependencies=[Depends(verify_api_key)],
)
async def list_scheduled_tasks() -> list[dict]:
    return scheduler.list_scheduled_tasks()


@router.delete(
    "/scheduled-task/{task_id}",
    dependencies=[Depends(verify_api_key)],
)
async def delete_scheduled_task(task_id: str) -> dict:
    if scheduler.remove_scheduled_task(task_id):
        return {"status": "deleted", "task_id": task_id}
    raise HTTPException(
        status_code=404, detail="Scheduled task not found"
    )


@router.post(
    "/scheduled-task/{task_id}/enable",
    dependencies=[Depends(verify_api_key)],
)
async def enable_scheduled_task(task_id: str) -> dict:
    if scheduler.enable_scheduled_task(task_id):
        return {"status": "enabled", "task_id": task_id}
    raise HTTPException(
        status_code=404, detail="Scheduled task not found"
    )


@router.post(
    "/scheduled-task/{task_id}/disable",
    dependencies=[Depends(verify_api_key)],
)
async def disable_scheduled_task(task_id: str) -> dict:
    if scheduler.disable_scheduled_task(task_id):
        return {"status": "disabled", "task_id": task_id}
    raise HTTPException(
        status_code=404, detail="Scheduled task not found"
    )


# ============================================================
# VIRTUAL AI API (OpenAI-compatible)
# ============================================================


def _verify_beta_api_key(request: Request) -> bool:
    if not settings.beta_api_key:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        import secrets
        return secrets.compare_digest(token, settings.beta_api_key)
    return False


@ai_router.post("/chat/completions")
async def chat_completions(request: Request, req: VirtualAIRequest):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")

    if req.model != settings.virtual_model_name:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {req.model}. Use {settings.virtual_model_name}",
        )

    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages required")

    try:
        response = await orchestrator.process(req)
        return response.model_dump()
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error(f"AI workflow error: {e}")
        raise HTTPException(status_code=500, detail="Internal AI error")


@ai_router.get("/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": settings.virtual_model_name,
                "object": "model",
                "created": 1700000000,
                "owned_by": "beta-ai",
            }
        ],
    }


@ai_router.get("/browser/screenshot/{task_id}")
async def get_browser_screenshot(
    request: Request, task_id: str
):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")

    tm = _get_task_manager(request)
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    screenshot_path = task.get("screenshot_path")
    if not screenshot_path or not os.path.exists(screenshot_path):
        return {"screenshot": None}

    import base64
    with open(screenshot_path, "rb") as f:
        screenshot_b64 = base64.b64encode(f.read()).decode()

    return {"screenshot": screenshot_b64}


@ai_router.get("/browser/status")
async def get_browser_status(request: Request):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")

    tm = _get_task_manager(request)
    browser_running = tm._browser is not None and tm._browser.service.process is not None if tm._browser else False
    return {
        "browser_running": browser_running,
        "engine": settings.browser_engine,
    }


@ai_router.post("/browser/navigate")
async def browser_navigate(request: Request):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()
    url = body.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    tm = _get_task_manager(request)
    try:
        tm._ensure_browser()
        from backend.browser.driver import navigate_safe
        result = await asyncio.to_thread(navigate_safe, tm._browser, url)
        return {"status": "ok" if result else "failed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# CHAT HISTORY
# ============================================================


@ai_router.get("/chat/sessions")
async def list_chat_sessions(request: Request):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"sessions": chat_history.list_sessions()}


@ai_router.get("/chat/sessions/{session_id}")
async def get_chat_session(request: Request, session_id: str):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    messages = chat_history.get_session_messages(session_id)
    return {
        "session_id": session_id,
        "messages": [m.model_dump() for m in messages],
    }


@ai_router.post("/chat/sessions/{session_id}/clear")
async def clear_chat_session(request: Request, session_id: str):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    chat_history.clear_session(session_id)
    return {"status": "cleared"}


@ai_router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(request: Request, session_id: str):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    chat_history.delete_session(session_id)
    return {"status": "deleted"}


@ai_router.post("/chat/send")
async def chat_send(request: Request):
    if not _verify_beta_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "")
    file_context = body.get("file_context", "")

    if not message:
        raise HTTPException(status_code=400, detail="Empty message")

    session = chat_history.get_or_create_session(session_id)
    chat_history.add_message(session.session_id, "user", message)

    messages = [{"role": m.role, "content": m.content} for m in session.messages]
    if file_context:
        messages.insert(-1, {"role": "system", "content": f"Attached file:\n{file_context[:8000]}"})

    try:
        ai_req = VirtualAIRequest(
            model=settings.virtual_model_name,
            messages=messages,
        )
        response = await orchestrator.process(ai_req)
        assistant_msg = response.choices[0].message["content"]
        chat_history.add_message(session.session_id, "assistant", assistant_msg)

        return {
            "response": assistant_msg,
            "session_id": session.session_id,
        }
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="AI error")


# ============================================================
# CLIENT MANAGEMENT (Windows Browser Agent)
# ============================================================


@client_router.post("/register")
async def register_client(request: Request):
    body = await request.json()
    client_id = body.get("client_id", "")
    token = body.get("token", "")

    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")

    if settings.api_auth_token and token != settings.api_auth_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    info = await client_manager.register_client(client_id, None)
    return {"status": "registered", "client_id": info.client_id}


@client_router.get("/status")
async def client_status():
    clients = client_manager.get_all_clients()
    return [
        {
            "client_id": c.client_id,
            "status": c.status,
            "browser_status": c.browser_status,
            "current_task": c.current_task,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
        }
        for c in clients
    ]


@client_router.get("/ready")
async def get_ready_client():
    cid = client_manager.get_ready_client()
    if cid:
        return {"client_id": cid}
    raise HTTPException(status_code=404, detail="No ready client")


@client_router.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    await websocket.accept()

    client_id = None
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        msg = parse_message(raw)
        if not msg or msg.get("type") != "CLIENT_REGISTER":
            await websocket.close(code=4001, reason="Expected CLIENT_REGISTER")
            return

        client_id = msg.get("client_id", "")
        token = msg.get("payload", {}).get("token", "")

        if settings.api_auth_token and token != settings.api_auth_token:
            await websocket.close(code=4003, reason="Unauthorized")
            return

        await client_manager.register_client(client_id, websocket)
        await websocket.send_text(json.dumps(msg_client_registered(client_id)))

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = parse_message(raw)
                if not msg:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "CLIENT_READY":
                    await client_manager.update_client_status(client_id, browser_status="ready")
                    logger.info(f"Client {client_id} browser ready")

                elif msg_type == "BROWSER_READY":
                    await client_manager.update_client_status(client_id, browser_status="ready")

                elif msg_type == "BROWSER_ERROR":
                    await client_manager.update_client_status(client_id, browser_status="error")
                    error = msg.get("payload", {}).get("error", "unknown")
                    task_id = msg.get("task_id")
                    if task_id:
                        await client_manager.release_task(client_id, task_id)

                elif msg_type == "TASK_STARTED":
                    task_id = msg.get("task_id", "")
                    logger.info(f"Task {task_id} started by {client_id}")

                elif msg_type == "TASK_PROGRESS":
                    task_id = msg.get("task_id", "")
                    logger.debug(f"Task {task_id} progress from {client_id}")

                elif msg_type == "TASK_RESULT":
                    task_id = msg.get("task_id", "")
                    await client_manager.release_task(client_id, task_id)
                    logger.info(f"Task {task_id} completed by {client_id}")

                elif msg_type == "TASK_ERROR":
                    task_id = msg.get("task_id", "")
                    await client_manager.release_task(client_id, task_id)

                elif msg_type == "CLIENT_HEARTBEAT":
                    await client_manager.update_client_status(client_id)
                    await websocket.send_text(json.dumps(msg_heartbeat("server")))

            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps(msg_heartbeat("server")))

    except asyncio.TimeoutError:
        logger.warning("Agent registration timeout")
    except WebSocketDisconnect:
        logger.info(f"Agent {client_id} disconnected")
    except Exception as e:
        logger.error(f"Agent WebSocket error: {e}")
    finally:
        if client_id:
            await client_manager.unregister_client(client_id)


# ============================================================
# PROXY MANAGEMENT
# ============================================================


@router.get(
    "/proxy/list",
    dependencies=[Depends(verify_api_key)],
)
async def list_proxies() -> dict:
    from backend.browser.proxy_manager import proxy_manager
    return {
        "count": proxy_manager.count,
        "enabled": proxy_manager.enabled,
        "proxies": proxy_manager.get_all(),
    }


@router.post(
    "/proxy/reload",
    dependencies=[Depends(verify_api_key)],
)
async def reload_proxies() -> dict:
    from backend.browser.proxy_manager import proxy_manager
    count = proxy_manager.reload()
    return {"status": "reloaded", "count": count}


@router.get(
    "/proxy/next",
    dependencies=[Depends(verify_api_key)],
)
async def get_next_proxy() -> dict:
    from backend.browser.proxy_manager import proxy_manager
    entry = proxy_manager.get_next()
    if entry:
        return {"ip": entry.ip, "port": entry.port, "protocol": entry.protocol}
    return {"error": "No proxies available"}
