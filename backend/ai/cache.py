from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ResponseCache:
    def __init__(self, max_size: int = 500, ttl_seconds: int = 600):
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def _make_key(self, agent: str, messages: list[dict], model: str = "") -> str:
        content = json.dumps({"a": agent, "m": messages, "mo": model}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def get(self, agent: str, messages: list[dict], model: str = "") -> Optional[dict]:
        key = self._make_key(agent, messages, model)
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        if time.time() - entry["created"] > self._ttl:
            del self._cache[key]
            self._misses += 1
            return None

        self._cache.move_to_end(key)
        self._hits += 1
        logger.debug("Cache hit: %s (age=%.1fs)", agent, time.time() - entry["created"])
        return entry["response"]

    def set(self, agent: str, messages: list[dict], response: dict, model: str = "") -> None:
        key = self._make_key(agent, messages, model)

        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)

        self._cache[key] = {
            "response": response,
            "created": time.time(),
        }

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def cleanup(self) -> int:
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v["created"] > self._ttl]
        for k in expired:
            del self._cache[k]
        return len(expired)

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(total, 1) * 100, 1),
            "ttl_seconds": self._ttl,
        }


response_cache = ResponseCache()
