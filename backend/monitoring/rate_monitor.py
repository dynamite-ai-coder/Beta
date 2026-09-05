from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KeyStats:
    calls: int = 0
    errors: int = 0
    rate_limited: int = 0
    last_used: float = 0.0
    last_error: float = 0.0
    total_tokens: int = 0
    avg_latency_ms: float = 0.0
    _latencies: list = field(default_factory=list)

    def record_call(self, latency_ms: float = 0, tokens: int = 0) -> None:
        self.calls += 1
        self.last_used = time.time()
        self.total_tokens += tokens
        if latency_ms > 0:
            self._latencies.append(latency_ms)
            if len(self._latencies) > 100:
                self._latencies = self._latencies[-50:]
            self.avg_latency_ms = sum(self._latencies) / len(self._latencies)

    def record_error(self, is_rate_limit: bool = False) -> None:
        self.errors += 1
        self.last_error = time.time()
        if is_rate_limit:
            self.rate_limited += 1

    @property
    def rpm(self) -> float:
        now = time.time()
        recent = [t for t in self._latencies if now - (self.last_used - t) < 60]
        return len(recent)

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "errors": self.errors,
            "rate_limited": self.rate_limited,
            "last_used": self.last_used,
            "last_error": self.last_error,
            "total_tokens": self.total_tokens,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "error_rate": round(self.errors / max(self.calls, 1) * 100, 1),
        }


class RateLimitMonitor:
    def __init__(self):
        self._keys: dict[str, KeyStats] = {}
        self._start_time = time.time()

    def track(self, key: str) -> None:
        if key not in self._keys:
            self._keys[key] = KeyStats()

    def record_call(self, key: str, latency_ms: float = 0, tokens: int = 0) -> None:
        if key not in self._keys:
            self._keys[key] = KeyStats()
        self._keys[key].record_call(latency_ms, tokens)

    def record_error(self, key: str, is_rate_limit: bool = False) -> None:
        if key not in self._keys:
            self._keys[key] = KeyStats()
        self._keys[key].record_error(is_rate_limit)

    def get_stats(self) -> dict:
        total_calls = sum(s.calls for s in self._keys.values())
        total_errors = sum(s.errors for s in self._keys.values())
        total_rate_limited = sum(s.rate_limited for s in self._keys.values())
        total_tokens = sum(s.total_tokens for s in self._keys.values())

        keys = {}
        for k, v in self._keys.items():
            masked = f"...{k[-6:]}" if len(k) > 6 else "***"
            keys[masked] = v.to_dict()

        return {
            "uptime_seconds": int(time.time() - self._start_time),
            "total_calls": total_calls,
            "total_errors": total_errors,
            "total_rate_limited": total_rate_limited,
            "total_tokens": total_tokens,
            "error_rate": round(total_errors / max(total_calls, 1) * 100, 1),
            "keys_count": len(self._keys),
            "keys": keys,
        }

    def get_key_stats(self, key: str) -> Optional[dict]:
        stats = self._keys.get(key)
        return stats.to_dict() if stats else None


rate_monitor = RateLimitMonitor()
