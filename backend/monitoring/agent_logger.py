from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentLog:
    timestamp: float
    agent: str
    task_id: str
    duration_ms: float
    success: bool
    tokens: int = 0
    confidence: float = 0.0
    error: str = ""
    input_preview: str = ""
    output_preview: str = ""
    cached: bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "agent": self.agent,
            "task_id": self.task_id,
            "duration_ms": round(self.duration_ms, 1),
            "success": self.success,
            "tokens": self.tokens,
            "confidence": round(self.confidence, 2),
            "error": self.error,
            "input_preview": self.input_preview[:100],
            "output_preview": self.output_preview[:200],
            "cached": self.cached,
        }


class AgentLogger:
    def __init__(self, max_logs: int = 1000):
        self._logs: list[AgentLog] = []
        self._max_logs = max_logs
        self._agent_stats: dict[str, dict] = defaultdict(lambda: {
            "calls": 0, "success": 0, "errors": 0,
            "total_ms": 0, "total_tokens": 0, "latencies": [],
        })

    def log(
        self,
        agent: str,
        task_id: str,
        duration_ms: float,
        success: bool,
        tokens: int = 0,
        confidence: float = 0.0,
        error: str = "",
        input_preview: str = "",
        output_preview: str = "",
        cached: bool = False,
    ) -> None:
        entry = AgentLog(
            timestamp=time.time(),
            agent=agent,
            task_id=task_id,
            duration_ms=duration_ms,
            success=success,
            tokens=tokens,
            confidence=confidence,
            error=error,
            input_preview=input_preview,
            output_preview=output_preview,
            cached=cached,
        )

        self._logs.append(entry)
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

        stats = self._agent_stats[agent]
        stats["calls"] += 1
        if success:
            stats["success"] += 1
        else:
            stats["errors"] += 1
        stats["total_ms"] += duration_ms
        stats["total_tokens"] += tokens
        stats["latencies"].append(duration_ms)
        if len(stats["latencies"]) > 100:
            stats["latencies"] = stats["latencies"][-50:]

        if success:
            logger.info(
                "Agent %s [%s]: %.0fms, tokens=%d, conf=%.2f%s",
                agent, task_id[:12], duration_ms, tokens, confidence,
                " (cached)" if cached else "",
            )
        else:
            logger.warning(
                "Agent %s [%s]: FAILED %.0fms, error=%s",
                agent, task_id[:12], duration_ms, error[:100],
            )

    def get_recent(self, count: int = 50, agent: str = None) -> list[dict]:
        logs = self._logs
        if agent:
            logs = [l for l in logs if l.agent == agent]
        return [l.to_dict() for l in logs[-count:]]

    def get_agent_stats(self, agent: str = None) -> dict:
        if agent:
            stats = self._agent_stats.get(agent)
            if not stats:
                return {}
            latencies = stats["latencies"]
            return {
                "agent": agent,
                "calls": stats["calls"],
                "success": stats["success"],
                "errors": stats["errors"],
                "success_rate": round(stats["success"] / max(stats["calls"], 1) * 100, 1),
                "avg_latency_ms": round(stats["total_ms"] / max(stats["calls"], 1), 1),
                "p50_latency_ms": round(sorted(latencies)[len(latencies) // 2] if latencies else 0, 1),
                "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0, 1),
                "total_tokens": stats["total_tokens"],
                "avg_tokens_per_call": round(stats["total_tokens"] / max(stats["calls"], 1)),
            }

        result = {}
        for name in self._agent_stats:
            result[name] = self.get_agent_stats(name)
        return result

    def get_workflow_stats(self, task_id: str) -> list[dict]:
        return [l.to_dict() for l in self._logs if l.task_id == task_id]

    def get_summary(self) -> dict:
        total_calls = sum(s["calls"] for s in self._agent_stats.values())
        total_success = sum(s["success"] for s in self._agent_stats.values())
        total_errors = sum(s["errors"] for s in self._agent_stats.values())
        total_tokens = sum(s["total_tokens"] for s in self._agent_stats.values())

        all_latencies = []
        for s in self._agent_stats.values():
            all_latencies.extend(s["latencies"])

        all_latencies.sort()
        n = len(all_latencies)

        return {
            "total_calls": total_calls,
            "total_success": total_success,
            "total_errors": total_errors,
            "total_tokens": total_tokens,
            "success_rate": round(total_success / max(total_calls, 1) * 100, 1),
            "avg_latency_ms": round(sum(all_latencies) / max(n, 1), 1),
            "p50_latency_ms": round(all_latencies[n // 2] if n else 0, 1),
            "p95_latency_ms": round(all_latencies[int(n * 0.95)] if n else 0, 1),
            "agents": len(self._agent_stats),
        }


agent_logger = AgentLogger()
