from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

DEFAULT_INSTRUCTION = "Log in with the provided credentials"


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskRow(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    state: Mapped[str] = mapped_column(String(32), default="QUEUED")
    target_url: Mapped[str] = mapped_column(String(2048))
    username: Mapped[str] = mapped_column(String(512))
    password: Mapped[str] = mapped_column(String(1024))
    instruction: Mapped[str] = mapped_column(Text, default=DEFAULT_INSTRUCTION)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    events: Mapped[list[EventRow]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "target_url": self.target_url,
            "username": self.username,
            "password": self.password,
            "instruction": self.instruction,
            "result": self.result,
            "reason": self.reason,
            "screenshot_path": self.screenshot_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.task_id", ondelete="CASCADE")
    )
    event: Mapped[str] = mapped_column(String(64))
    data: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    task: Mapped[TaskRow] = relationship(back_populates="events")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "event": self.event,
            "data": self.data,
            "timestamp": (
                self.timestamp.isoformat() if self.timestamp else None
            ),
        }


class ScheduledTaskRow(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(256))
    target_url: Mapped[str] = mapped_column(String(2048))
    username: Mapped[str] = mapped_column(String(512))
    password: Mapped[str] = mapped_column(String(1024))
    instruction: Mapped[str] = mapped_column(Text, default=DEFAULT_INSTRUCTION)
    cron_expression: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(default=True)
    last_run: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "target_url": self.target_url,
            "username": self.username,
            "instruction": self.instruction,
            "cron_expression": self.cron_expression,
            "enabled": self.enabled,
            "last_run": (
                self.last_run.isoformat() if self.last_run else None
            ),
            "next_run": (
                self.next_run.isoformat() if self.next_run else None
            ),
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
