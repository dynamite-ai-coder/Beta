from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router, ai_router, client_router
from backend.config import settings
from backend.database import init_db
from backend.models.schemas import HealthResponse
from backend.monitoring.metrics import (
    get_metrics,
    metrics_middleware,
    update_task_metrics,
)
from backend.security.auth import rate_limit_middleware
from backend.security.https import https_redirect_middleware
from backend.tasks.manager import TaskManager
from backend.tasks.scheduler import scheduler

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

task_manager = TaskManager()
proxy_client: httpx.AsyncClient | None = None
_status_cache: dict = {"data": None, "time": 0.0}
_status_cache_lock = __import__("asyncio").Lock()
STATUS_CACHE_TTL = 5.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global proxy_client
    from backend.ai.llm_provider import key_pool
    logger.info("Starting Browser Automation API")
    os.makedirs(settings.img_dir, exist_ok=True)
    await init_db()
    key_pool.load()
    proxy_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    app.state.task_manager = task_manager
    await scheduler.start(task_manager)
    yield
    logger.info("Shutting down Browser Automation API")
    await scheduler.stop()
    await task_manager.cleanup_all()
    await proxy_client.aclose()


app = FastAPI(
    title="Beta Virtual AI API",
    description="Multi-agent AI system with browser automation",
    version="2.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.state.task_manager = task_manager

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(rate_limit_middleware)
app.middleware("http")(metrics_middleware)
if not settings.debug:
    app.middleware("http")(https_redirect_middleware)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info(
        "%s %s %.2fms %s",
        request.method,
        request.url.path,
        duration_ms,
        request.state.request_id,
    )
    return response

app.include_router(router, prefix="/api/v1")
app.include_router(ai_router, prefix="/v1")
app.include_router(client_router, prefix="/api/clients")

static_dir = os.path.join(
    os.path.dirname(__file__), "static"
)
if os.path.exists(static_dir):
    app.mount(
        "/static",
        StaticFiles(directory=static_dir),
        name="static",
    )

DASHBOARD_NOT_FOUND = (
    "<h1>Browser Automation API</h1>"
    "<p>Dashboard not found.</p>"
)


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    index_path = os.path.join(
        os.path.dirname(__file__), "static", "index.html"
    )
    if os.path.exists(index_path):
        with open(index_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content=DASHBOARD_NOT_FOUND)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    update_task_metrics(task_manager)
    return HealthResponse(
        status="ok",
        version="2.0.0",
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/metrics")
async def metrics() -> Response:
    update_task_metrics(task_manager)
    return Response(
        content=get_metrics(),
        media_type="text/plain",
    )


CLIENT_URL = os.environ.get("CLIENT_URL", "http://localhost:23400")

CLIENT_PATHS = (
    "/api/status",
    "/api/chat/",
    "/api/tor/",
    "/api/upload",
    "/api/run",
    "/api/ngrok",
    "/api/localai/",
    "/api/plugins",
    "/api/preview/",
)


async def _proxy_request(
    request: Request,
    target: str,
) -> Response:
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    try:
        resp = await proxy_client.request(
            method=request.method,
            url=target,
            headers=headers,
            content=body if body else None,
        )
    except httpx.ConnectError:
        return JSONResponse(
            status_code=502,
            content={"detail": "Client service unavailable"},
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"detail": "Client service timeout"},
        )
    excluded = {
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
    }
    resp_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in excluded
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
    )


@app.api_route(
    "/ui/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy_ui(request: Request, path: str = ""):
    return await _proxy_request(request, f"{CLIENT_URL}/{path}")


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy_client_api(request: Request, path: str = ""):
    req_path = f"/{path}"
    if req_path == "/api/status":
        now = time.monotonic()
        async with _status_cache_lock:
            if _status_cache["data"] and now - _status_cache["time"] < STATUS_CACHE_TTL:
                return Response(
                    content=_status_cache["data"],
                    media_type="application/json",
                )
        resp = await _proxy_request(request, f"{CLIENT_URL}/{path}")
        if resp.status_code == 200:
            async with _status_cache_lock:
                _status_cache["data"] = resp.body
                _status_cache["time"] = time.monotonic()
        return resp
    if any(req_path.startswith(p) for p in CLIENT_PATHS):
        return await _proxy_request(request, f"{CLIENT_URL}/{path}")
    return JSONResponse(
        status_code=404,
        content={"detail": "Not found"},
    )


@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
