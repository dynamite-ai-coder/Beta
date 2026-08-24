from __future__ import annotations

import asyncio
import json
import logging
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

from backend.config import is_url_allowed
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

logger = logging.getLogger(__name__)
router = APIRouter()

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
