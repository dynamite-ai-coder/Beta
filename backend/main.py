from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Browser Automation API")
    os.makedirs(settings.img_dir, exist_ok=True)
    await init_db()
    app.state.task_manager = task_manager
    await scheduler.start(task_manager)
    yield
    logger.info("Shutting down Browser Automation API")
    await scheduler.stop()
    await task_manager.cleanup_all()


app = FastAPI(
    title="Browser Automation API",
    description="Authorized browser testing tool",
    version="1.1.0",
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

app.include_router(router, prefix="/api/v1")

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
        version="1.1.0",
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/metrics")
async def metrics() -> Response:
    update_task_metrics(task_manager)
    return Response(
        content=get_metrics(),
        media_type="text/plain",
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
