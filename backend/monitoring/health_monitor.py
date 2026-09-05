from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentHealth:
    name: str
    failures: int = 0
    last_failure: float = 0.0
    last_success: float = 0.0
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    is_healthy: bool = True
    cooldown_until: float = 0.0

    def record_success(self) -> None:
        self.failures = 0
        self.consecutive_failures = 0
        self.last_success = time.time()
        self.total_successes += 1
        self.is_healthy = True
        self.cooldown_until = 0.0

    def record_failure(self, max_failures: int = 3, cooldown_seconds: int = 60) -> None:
        self.failures += 1
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure = time.time()

        if self.consecutive_failures >= max_failures:
            self.is_healthy = False
            self.cooldown_until = time.time() + cooldown_seconds
            logger.warning(
                "Agent %s marked unhealthy after %d consecutive failures, "
                "cooldown %ds",
                self.name, self.consecutive_failures, cooldown_seconds,
            )

    def can_execute(self) -> bool:
        if self.is_healthy:
            return True
        if time.time() >= self.cooldown_until:
            self.is_healthy = True
            self.consecutive_failures = 0
            logger.info("Agent %s cooldown expired, marking healthy", self.name)
            return True
        return False

    @property
    def success_rate(self) -> float:
        total = self.total_successes + self.total_failures
        return self.total_successes / max(total, 1) * 100

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_healthy": self.is_healthy,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "success_rate": round(self.success_rate, 1),
            "cooldown_remaining": max(0, round(self.cooldown_until - time.time())),
        }


class HealthMonitor:
    def __init__(self, max_failures: int = 3, cooldown_seconds: int = 60):
        self._agents: dict[str, AgentHealth] = {}
        self._max_failures = max_failures
        self._cooldown_seconds = cooldown_seconds

    def get_agent(self, name: str) -> AgentHealth:
        if name not in self._agents:
            self._agents[name] = AgentHealth(name=name)
        return self._agents[name]

    def record_success(self, agent: str) -> None:
        self.get_agent(agent).record_success()

    def record_failure(self, agent: str) -> None:
        self.get_agent(agent).record_failure(self._max_failures, self._cooldown_seconds)

    def can_execute(self, agent: str) -> bool:
        return self.get_agent(agent).can_execute()

    def get_healthy_agents(self) -> list[str]:
        return [name for name, h in self._agents.items() if h.can_execute()]

    def get_unhealthy_agents(self) -> list[str]:
        return [name for name, h in self._agents.items() if not h.can_execute()]

    def get_stats(self) -> dict:
        return {
            "agents": {name: h.to_dict() for name, h in self._agents.items()},
            "healthy_count": len(self.get_healthy_agents()),
            "unhealthy_count": len(self.get_unhealthy_agents()),
            "max_failures": self._max_failures,
            "cooldown_seconds": self._cooldown_seconds,
        }


health_monitor = HealthMonitor()
