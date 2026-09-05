from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ABTest:
    id: str
    name: str
    model_a: str
    model_b: str
    traffic_split: float = 0.5
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    results_a: list = field(default_factory=list)
    results_b: list = field(default_factory=list)

    def route(self) -> str:
        if not self.enabled:
            return "A"
        return "A" if random.random() < self.traffic_split else "B"

    def record(self, variant: str, latency_ms: float, success: bool, tokens: int = 0) -> None:
        entry = {"latency_ms": latency_ms, "success": success, "tokens": tokens, "time": time.time()}
        if variant == "A":
            self.results_a.append(entry)
        else:
            self.results_b.append(entry)

    def get_stats(self) -> dict:
        def calc(results):
            if not results:
                return {"calls": 0, "success_rate": 0, "avg_latency_ms": 0, "total_tokens": 0}
            successes = sum(1 for r in results if r["success"])
            return {
                "calls": len(results),
                "success_rate": round(successes / len(results) * 100, 1),
                "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / len(results), 1),
                "total_tokens": sum(r["tokens"] for r in results),
            }

        return {
            "id": self.id,
            "name": self.name,
            "model_a": self.model_a,
            "model_b": self.model_b,
            "traffic_split": self.traffic_split,
            "enabled": self.enabled,
            "variant_a": calc(self.results_a),
            "variant_b": calc(self.results_b),
        }


class ABTestManager:
    def __init__(self):
        self._tests: dict[str, ABTest] = {}

    def create(self, name: str, model_a: str, model_b: str, split: float = 0.5) -> ABTest:
        test_id = f"ab-{len(self._tests) + 1}"
        test = ABTest(
            id=test_id, name=name, model_a=model_a,
            model_b=model_b, traffic_split=split,
        )
        self._tests[test_id] = test
        logger.info("A/B test created: %s (%s vs %s)", name, model_a, model_b)
        return test

    def get(self, test_id: str) -> Optional[ABTest]:
        return self._tests.get(test_id)

    def route(self, test_id: str) -> tuple[str, str]:
        test = self._tests.get(test_id)
        if not test:
            return ("A", "")
        variant = test.route()
        model = test.model_a if variant == "A" else test.model_b
        return (variant, model)

    def record(self, test_id: str, variant: str, latency_ms: float, success: bool, tokens: int = 0) -> None:
        test = self._tests.get(test_id)
        if test:
            test.record(variant, latency_ms, success, tokens)

    def list_all(self) -> list[dict]:
        return [t.get_stats() for t in self._tests.values()]

    def delete(self, test_id: str) -> bool:
        if test_id in self._tests:
            del self._tests[test_id]
            return True
        return False


ab_manager = ABTestManager()
