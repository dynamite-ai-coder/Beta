from __future__ import annotations

import time

from fastapi import Request, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

ACTIVE_TASKS = Gauge(
    "active_tasks",
    "Number of active tasks",
    ["state"],
)

TOTAL_TASKS = Counter(
    "tasks_total",
    "Total tasks created",
    ["state"],
)

AI_REQUESTS = Counter(
    "ai_requests_total",
    "Total AI provider requests",
    ["provider", "status"],
)

AI_LATENCY = Histogram(
    "ai_request_duration_seconds",
    "AI request latency",
    ["provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

BROWSER_SESSIONS = Gauge(
    "browser_sessions",
    "Number of active browser sessions",
)

WEBSOCKET_CONNECTIONS = Gauge(
    "websocket_connections",
    "Number of active WebSocket connections",
)

TASK_STATES = [
    "QUEUED", "STARTING", "RUNNING",
    "WAITING_FOR_MANUAL_ACTION", "SUCCESS",
    "FAILURE", "STOPPED", "TIMEOUT",
]


async def metrics_middleware(request: Request, call_next) -> Response:
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
    ).inc()

    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path,
    ).observe(duration)

    return response


def get_metrics() -> bytes:
    return generate_latest()


def update_task_metrics(task_manager) -> None:
    state_counts: dict[str, int] = {}
    for task in task_manager._tasks.values():
        state = task["state"]
        state_val = state.value if hasattr(state, "value") else str(state)
        state_counts[state_val] = state_counts.get(state_val, 0) + 1

    for state in TASK_STATES:
        ACTIVE_TASKS.labels(state=state).set(state_counts.get(state, 0))

    from backend.services.client_manager import client_manager
    ready_clients = sum(
        1 for c in client_manager.get_all_clients()
        if c.browser_status == "ready"
    )
    BROWSER_SESSIONS.set(ready_clients)
