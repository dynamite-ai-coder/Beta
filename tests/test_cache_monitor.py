import time
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.ai.cache import ResponseCache
from backend.monitoring.rate_monitor import RateLimitMonitor, KeyStats


class TestResponseCache:
    def test_set_get(self):
        cache = ResponseCache(max_size=10, ttl_seconds=60)
        messages = [{"role": "user", "content": "test"}]
        cache.set("planner", messages, {"raw": "response", "parsed": {}, "confidence": 0.8, "tokens": 100})
        result = cache.get("planner", messages)
        assert result is not None
        assert result["raw"] == "response"

    def test_cache_miss(self):
        cache = ResponseCache(max_size=10, ttl_seconds=60)
        result = cache.get("planner", [{"role": "user", "content": "test"}])
        assert result is None

    def test_cache_expiry(self):
        cache = ResponseCache(max_size=10, ttl_seconds=0)
        messages = [{"role": "user", "content": "test"}]
        cache.set("planner", messages, {"raw": "response"})
        time.sleep(0.01)
        result = cache.get("planner", messages)
        assert result is None

    def test_cache_max_size(self):
        cache = ResponseCache(max_size=3, ttl_seconds=60)
        for i in range(5):
            cache.set("agent", [{"role": "user", "content": f"msg{i}"}], {"raw": f"resp{i}"})
        assert len(cache._cache) == 3

    def test_cache_stats(self):
        cache = ResponseCache(max_size=10, ttl_seconds=60)
        messages = [{"role": "user", "content": "test"}]
        cache.set("planner", messages, {"raw": "response"})
        cache.get("planner", messages)
        cache.get("planner", [{"role": "user", "content": "other"}])
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_cache_cleanup(self):
        cache = ResponseCache(max_size=10, ttl_seconds=0)
        messages = [{"role": "user", "content": "test"}]
        cache.set("planner", messages, {"raw": "response"})
        time.sleep(0.01)
        cleaned = cache.cleanup()
        assert cleaned == 1
        assert len(cache._cache) == 0


class TestRateLimitMonitor:
    def test_record_call(self):
        monitor = RateLimitMonitor()
        monitor.record_call("key123", 100.0, 150)
        stats = monitor.get_stats()
        assert stats["total_calls"] == 1
        assert stats["total_tokens"] == 150

    def test_record_error(self):
        monitor = RateLimitMonitor()
        monitor.record_error("key123", is_rate_limit=True)
        stats = monitor.get_stats()
        assert stats["total_errors"] == 1
        assert stats["total_rate_limited"] == 1

    def test_multiple_keys(self):
        monitor = RateLimitMonitor()
        monitor.record_call("key1", 100, 100)
        monitor.record_call("key2", 200, 200)
        stats = monitor.get_stats()
        assert stats["total_calls"] == 2
        assert stats["keys_count"] == 2

    def test_error_rate(self):
        monitor = RateLimitMonitor()
        for _ in range(8):
            monitor.record_call("key1", 100, 50)
        for _ in range(2):
            monitor.record_error("key1")
        stats = monitor.get_stats()
        assert stats["error_rate"] == 25.0

    def test_key_stats(self):
        monitor = RateLimitMonitor()
        monitor.record_call("key123", 150.0, 200)
        stats = monitor.get_key_stats("key123")
        assert stats is not None
        assert stats["calls"] == 1
        assert stats["total_tokens"] == 200
        assert stats["avg_latency_ms"] == 150.0

    def test_masked_key(self):
        monitor = RateLimitMonitor()
        monitor.record_call("sk-1234567890abcdef", 100, 50)
        stats = monitor.get_stats()
        assert "..." in list(stats["keys"].keys())[0]
