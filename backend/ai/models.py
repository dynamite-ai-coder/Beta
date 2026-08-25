from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field
from backend.ai.agent_roles import AgentRole


class AgentMessage(BaseModel):
    agent: AgentRole
    type: str = "analysis"
    task_id: str = ""
    content: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    recommendation: str = ""
    requested_action: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentOutput(BaseModel):
    agent: AgentRole
    raw_response: str = ""
    parsed: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    success: bool = True
    error: Optional[str] = None
    tokens_used: int = 0
    duration_ms: float = 0.0


class AIContext(BaseModel):
    task_id: str
    original_request: str
    plan: list[str] = Field(default_factory=list)
    agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    facts: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    browser_observations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    state: str = "initialized"
    final_answer: str = ""
    needs_browser: bool = False
    browser_task_payload: Optional[dict[str, Any]] = None
    deliberation_round: int = 0
    max_deliberation_rounds: int = 2

    def get_compact_summary(self, max_items: int = 5) -> str:
        lines = [f"Request: {self.original_request}"]
        if self.plan:
            lines.append(f"Plan: {', '.join(self.plan[:3])}")
        if self.facts:
            lines.append(f"Facts: {', '.join(self.facts[:max_items])}")
        if self.evidence:
            lines.append(f"Evidence: {', '.join(self.evidence[:max_items])}")
        if self.errors:
            lines.append(f"Errors: {', '.join(self.errors[:max_items])}")
        lines.append(f"Confidence: {self.confidence:.2f}")
        lines.append(f"Round: {self.deliberation_round}/{self.max_deliberation_rounds}")
        return "\n".join(lines)


class VirtualAIRequest(BaseModel):
    model: str = "beta-virtual-ai"
    messages: list[dict[str, str]]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    stream: bool = False


class VirtualAIChoice(BaseModel):
    index: int = 0
    message: dict[str, str]
    finish_reason: str = "stop"


class VirtualAIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class VirtualAIResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str = "beta-virtual-ai"
    choices: list[VirtualAIChoice]
    usage: VirtualAIUsage = Field(default_factory=VirtualAIUsage)


class BrowserTaskRequest(BaseModel):
    task_id: str
    actions: list[dict[str, Any]] = Field(default_factory=list)
    target_url: str = ""
    instruction: str = ""
    timeout: int = 300


class BrowserTaskResult(BaseModel):
    task_id: str
    status: str = "success"
    result: dict[str, Any] = Field(default_factory=dict)
    screenshots: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClientInfo(BaseModel):
    client_id: str
    status: str = "offline"
    last_seen: Optional[datetime] = None
    browser_status: str = "unknown"
    current_task: Optional[str] = None
    connection_id: Optional[str] = None


class WebSocketMessage(BaseModel):
    protocol_version: int = 1
    type: str
    task_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
