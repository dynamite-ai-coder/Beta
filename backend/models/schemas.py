from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class TaskState(str, Enum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_FOR_MANUAL_ACTION = "WAITING_FOR_MANUAL_ACTION"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    STOPPED = "STOPPED"
    TIMEOUT = "TIMEOUT"


class TaskRequest(BaseModel):
    target_url: str = Field(..., min_length=1, max_length=2048)
    username: str = Field(..., min_length=1, max_length=512)
    password: str = Field(..., min_length=1, max_length=1024)
    natural_language_instruction: str = Field(
        default="Log in with the provided credentials",
        max_length=4096,
    )

    @field_validator("target_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class TaskResponse(BaseModel):
    task_id: str
    state: TaskState
    target_url: str
    created_at: datetime
    updated_at: datetime
    message: str | None = None
    preview_url: str | None = None


class TaskResult(BaseModel):
    task_id: str
    state: TaskState
    target_url: str
    username: str
    result: str | None = None
    reason: str | None = None
    screenshot_path: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ManualActionRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=1024)


class AISelectors(BaseModel):
    username_selector: str
    password_selector: str
    submit_selector: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class BrowserAction(BaseModel):
    action: str = Field(
        ...,
        pattern="^(navigate|click|type|wait|inspect|screenshot|finish|request_manual_action)$",
    )
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    reason: str | None = None


class DOMElement(BaseModel):
    tag: str
    id: str | None = None
    name: str | None = None
    type: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    text: str | None = None
    role: str | None = None
    css_selector: str | None = None
    xpath: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EventMessage(BaseModel):
    event: str
    data: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
