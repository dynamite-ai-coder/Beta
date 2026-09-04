from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: str = ""


class ChatSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: str = ""


class ChatHistoryManager:
    def __init__(self, max_sessions: int = 100, max_messages_per_session: int = 200) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._max_sessions = max_sessions
        self._max_messages = max_messages_per_session

    def get_or_create_session(self, session_id: str | None = None) -> ChatSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        session = ChatSession(session_id=session_id or str(uuid.uuid4()))
        self._sessions[session.session_id] = session

        if len(self._sessions) > self._max_sessions:
            oldest = min(self._sessions.values(), key=lambda s: s.updated_at)
            del self._sessions[oldest.session_id]

        return session

    def add_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        session = self.get_or_create_session(session_id)
        msg = ChatMessage(role=role, content=content, session_id=session_id)
        session.messages.append(msg)
        session.updated_at = datetime.now(timezone.utc)

        if not session.title and role == "user":
            session.title = content[:50] + ("..." if len(content) > 50 else "")

        if len(session.messages) > self._max_messages:
            session.messages = session.messages[-self._max_messages:]

        return msg

    def get_session_messages(self, session_id: str) -> list[ChatMessage]:
        session = self._sessions.get(session_id)
        if session:
            return session.messages
        return []

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.updated_at,
            reverse=True
        )
        return [
            {
                "session_id": s.session_id,
                "title": s.title,
                "message_count": len(s.messages),
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
            for s in sessions[:50]
        ]

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def clear_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session:
            session.messages.clear()
            session.updated_at = datetime.now(timezone.utc)
            return True
        return False


chat_history = ChatHistoryManager()
