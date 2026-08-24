from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.config import is_url_allowed
from backend.models.schemas import (
    ManualActionRequest,
    TaskRequest,
    TaskResponse,
    TaskState,
)
from backend.security.auth import (
    create_session_token,
    verify_api_key,
)
from backend.streaming.preview import preview_streamer
from backend.tasks.manager import TaskManager

logger = logging.getLogger(__name__)
router = APIRouter()

_task_manager = TaskManager()


@router.post("/task", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
async def create_task(request: Request, task_req: TaskRequest) -> TaskResponse:
    client_ip = request.client.host if request.client else "unknown"

    if not is_url_allowed(task_req.target_url):
        raise HTTPException(status_code=400, detail="Target URL is not allowed by policy")

    task_id = str(uuid.uuid4())

    task = await _task_manager.create_task(
        task_id=task_id,
        target_url=task_req.target_url,
        username=task_req.username,
        password=task_req.password,
        instruction=task_req.natural_language_instruction,
    )

    preview_token = create_session_token()
    task["preview_token"] = preview_token

    asyncio.create_task(_task_manager.execute_task(task_id))

    logger.info("Task created: %s from %s", task_id, client_ip)

    return TaskResponse(
        task_id=task_id,
        state=TaskState.QUEUED,
        target_url=task_req.target_url,
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        preview_url=f"/task/{task_id}/preview?token={preview_token}",
    )


@router.get("/task/{task_id}", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
async def get_task(task_id: str) -> TaskResponse:
    task = _task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = task["state"]
    if isinstance(state, str):
        state = TaskState(state)

    return TaskResponse(
        task_id=task_id,
        state=state,
        target_url=task["target_url"],
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        result=task.get("result"),
        reason=task.get("reason"),
    )


@router.get("/task/{task_id}/events", dependencies=[Depends(verify_api_key)])
async def get_task_events(task_id: str) -> list[dict]:
    task = _task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_manager.get_events(task_id)


@router.get("/task/{task_id}/preview", dependencies=[Depends(verify_api_key)])
async def get_task_preview(task_id: str, token: str) -> StreamingResponse:
    task = _task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.get("preview_token") != token:
        raise HTTPException(status_code=403, detail="Invalid preview token")

    await preview_streamer.start_stream(task_id, token)

    return StreamingResponse(
        preview_streamer.generate_mjpeg(task_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/task/{task_id}/manual-action", dependencies=[Depends(verify_api_key)])
async def manual_action(task_id: str, req: ManualActionRequest) -> dict:
    task = _task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = task["state"]
    if isinstance(state, str):
        state = TaskState(state)

    if state != TaskState.WAITING_FOR_MANUAL_ACTION:
        raise HTTPException(status_code=400, detail="Task is not waiting for manual action")

    continued = await _task_manager.manual_action_continue(task_id)
    if not continued:
        raise HTTPException(status_code=500, detail="Failed to resume task")

    return {"status": "resumed", "task_id": task_id}


@router.post("/task/{task_id}/stop", dependencies=[Depends(verify_api_key)])
async def stop_task(task_id: str) -> dict:
    task = _task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    stopped = await _task_manager.stop_task(task_id)
    if not stopped:
        raise HTTPException(status_code=400, detail="Could not stop task")

    return {"status": "stopped", "task_id": task_id}
