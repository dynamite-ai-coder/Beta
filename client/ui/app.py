from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from client.config import ClientConfig
from client.chat import ChatClient
from client.files.manager import FileManager

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


class LocalUI:
    def __init__(
        self,
        config: ClientConfig,
        chat_client: ChatClient,
        file_manager: FileManager,
    ) -> None:
        self._config = config
        self._chat = chat_client
        self._files = file_manager
        self._app = FastAPI(title="Beta Browser AI", docs_url=None, redoc_url=None)
        self._ws_clients: list = []
        self._browser_worker = None
        self._browser_preview = None
        self._current_task_id: Optional[str] = None
        self._current_preview_token: Optional[str] = None
        self._setup_routes()

    @property
    def app(self) -> FastAPI:
        return self._app

    def set_browser_worker(self, worker: Any) -> None:
        self._browser_worker = worker

    def set_browser_preview(self, preview: Any) -> None:
        self._browser_preview = preview

    def set_current_task(self, task_id: str, preview_token: str = "") -> None:
        self._current_task_id = task_id
        self._current_preview_token = preview_token

    def _setup_routes(self) -> None:
        app = self._app

        @app.get("/")
        async def index():
            template = BASE_DIR / "templates" / "index.html"
            return HTMLResponse(template.read_text(encoding="utf-8"))

        @app.get("/api/status")
        async def status():
            browser_ok = self._browser_worker is not None and self._browser_worker.is_ready if self._browser_worker else False
            ngrok_url = None
            try:
                async with httpx.AsyncClient(timeout=3.0) as c:
                    r = await c.get("http://localhost:4040/api/tunnels")
                    tunnels = r.json().get("tunnels", [])
                    for t in tunnels:
                        if t.get("proto") == "https":
                            ngrok_url = t.get("public_url")
                            break
            except Exception:
                pass
            return JSONResponse({
                "browser_connected": browser_ok,
                "ai_connected": True,
                "task_status": "idle",
                "client_id": self._config.client_id,
                "ngrok_url": ngrok_url,
            })

        @app.get("/api/chat/history")
        async def chat_history():
            return JSONResponse({"history": self._chat.history})

        @app.post("/api/chat/send")
        async def chat_send(request: Request):
            body = await request.json()
            message = body.get("message", "").strip()
            if not message:
                return JSONResponse({"error": "Empty message"}, status_code=400)

            file_context = body.get("file_context", "")
            response = await self._chat.send_message(message, file_context)
            return JSONResponse({"response": response, "history": self._chat.history})

        @app.post("/api/chat/clear")
        async def chat_clear():
            self._chat.clear_history()
            return JSONResponse({"status": "cleared"})

        @app.post("/api/tor/toggle")
        async def tor_toggle(request: Request):
            try:
                body = await request.json()
            except Exception:
                body = {}
            enabled = body.get("enabled", False)
            try:
                backend_url = os.environ.get("BACKEND_URL", "https://beta-fmp9.onrender.com")
                token = os.environ.get("API_AUTH_TOKEN", "")
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(
                        f"{backend_url}/api/tor/toggle",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"enabled": enabled},
                    )
                    if r.status_code == 200:
                        return JSONResponse({"status": "ok", "tor_enabled": enabled})
            except Exception:
                pass
            return JSONResponse({"status": "ok", "tor_enabled": enabled, "note": "local only"})

        @app.post("/api/upload")
        async def upload_file(request: Request):
            form = await request.form()
            if "file" not in form:
                return JSONResponse({"error": "No file"}, status_code=400)
            f = form["file"]
            content = await f.read()
            filename = f.filename or "unknown"
            valid, msg = self._files.validate_file(filename, len(content))
            if not valid:
                return JSONResponse({"error": msg}, status_code=400)

            text = self._files.extract_text(filename, content)
            info = self._files.get_file_info(filename, len(content))
            return JSONResponse({
                "status": "ok",
                "file_info": info,
                "extracted_text": text,
            })

        @app.get("/api/browser/screenshot")
        async def browser_screenshot():
            if self._browser_preview and self._browser_worker:
                b64 = await self._browser_preview.capture(self._browser_worker)
                if b64:
                    return JSONResponse({"screenshot": b64, "timestamp": time.time()})
            return JSONResponse({"screenshot": None})

        @app.get("/api/browser/status")
        async def browser_status():
            if self._browser_worker:
                url = await self._browser_worker.get_current_url() if self._browser_worker.is_ready else ""
                return JSONResponse({
                    "connected": self._browser_worker.is_ready,
                    "current_url": url,
                    "engine": self._config.browser_engine,
                })
            return JSONResponse({"connected": False, "current_url": "", "engine": self._config.browser_engine})

        @app.post("/api/browser/navigate")
        async def browser_navigate(request: Request):
            body = await request.json()
            url = body.get("url", "")
            if not url:
                return JSONResponse({"error": "No URL"}, status_code=400)
            if not self._browser_worker or not self._browser_worker.is_ready:
                return JSONResponse({"error": "Browser not ready"}, status_code=503)
            ok = await self._browser_worker.navigate(url)
            return JSONResponse({"status": "ok" if ok else "failed"})

        @app.get("/api/preview/tasks")
        async def preview_tasks():
            try:
                headers = {}
                if self._config.api_token:
                    headers["Authorization"] = f"Bearer {self._config.api_token}"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{self._config.backend_url}/api/v1/tasks",
                        headers=headers,
                        params={"limit": 5},
                    )
                    if resp.status_code == 200:
                        tasks = resp.json()
                        return JSONResponse({"tasks": tasks, "current_task_id": self._current_task_id})
                    return JSONResponse({"tasks": [], "error": f"Backend returned {resp.status_code}", "current_task_id": self._current_task_id})
            except Exception as e:
                logger.error(f"Preview tasks error: {e}")
                return JSONResponse({"tasks": [], "error": str(e), "current_task_id": self._current_task_id})

        @app.get("/api/preview/screenshot/{task_id}")
        async def preview_screenshot(task_id: str):
            try:
                headers = {}
                if self._config.api_token:
                    headers["Authorization"] = f"Bearer {self._config.api_token}"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{self._config.backend_url}/v1/browser/screenshot/{task_id}",
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        return JSONResponse(resp.json())
                    return JSONResponse({"screenshot": None, "error": f"Backend returned {resp.status_code}"})
            except Exception as e:
                logger.error(f"Preview screenshot error: {e}")
                return JSONResponse({"screenshot": None, "error": str(e)})

        @app.get("/api/preview")
        @app.get("/preview")
        async def preview_page():
            template = BASE_DIR / "templates" / "preview.html"
            if template.exists():
                return HTMLResponse(template.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Preview not available</h1>", status_code=404)

        @app.get("/api/preview/auto_task")
        async def preview_auto_task():
            try:
                headers = {}
                if self._config.api_token:
                    headers["Authorization"] = f"Bearer {self._config.api_token}"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{self._config.backend_url}/api/v1/tasks",
                        headers=headers,
                        params={"limit": 1, "state": "running"},
                    )
                    if resp.status_code == 200:
                        tasks = resp.json()
                        if tasks:
                            return JSONResponse({"task_id": tasks[0]["task_id"], "state": tasks[0]["state"]})
                    resp2 = await client.get(
                        f"{self._config.backend_url}/api/v1/tasks",
                        headers=headers,
                        params={"limit": 1},
                    )
                    if resp2.status_code == 200:
                        tasks2 = resp2.json()
                        if tasks2:
                            return JSONResponse({"task_id": tasks2[0]["task_id"], "state": tasks2[0]["state"]})
            except Exception as e:
                logger.error(f"Auto task error: {e}")
            return JSONResponse({"task_id": None, "state": None})

        @app.get("/api/preview/stream")
        async def preview_stream(request: Request):
            url = request.query_params.get("url", "https://example.com")
            fps = max(1, min(int(request.query_params.get("fps", 15)), 30))
            interval = 1.0 / fps

            async def generate():
                from client.plugins.manager import plugin_manager
                screenshot_plugin = plugin_manager.get("screenshot")

                while True:
                    try:
                        if screenshot_plugin:
                            result = await screenshot_plugin.execute(action="capture", url=url, width=1280, height=720)
                            b64 = result.get("screenshot", "")
                            if b64:
                                jpeg_bytes = base64.b64decode(b64)
                                if _HAS_PIL:
                                    try:
                                        img = Image.open(io.BytesIO(jpeg_bytes))
                                        img = img.resize((1280, 720), Image.LANCZOS)
                                        buf = io.BytesIO()
                                        img.save(buf, format="JPEG", quality=85, optimize=True)
                                        jpeg_bytes = buf.getvalue()
                                    except Exception:
                                        pass
                                yield (
                                    b"--frame\r\n"
                                    b"Content-Type: image/jpeg\r\n"
                                    b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
                                    + jpeg_bytes + b"\r\n"
                                )
                    except Exception as e:
                        logger.debug(f"Stream frame error: {e}")

                    await asyncio.sleep(interval)

            return StreamingResponse(
                generate(),
                media_type="multipart/x-mixed-replace; boundary=frame",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.get("/api/plugins")
        async def list_plugins():
            from client.plugins.manager import plugin_manager
            return JSONResponse({"plugins": plugin_manager.list_all()})

        @app.post("/api/plugins/execute")
        async def execute_plugin(request: Request):
            body = await request.json()
            plugin_name = body.get("name", "")
            action = body.get("action", "")
            params = body.get("params", {})
            if not plugin_name:
                return JSONResponse({"error": "Plugin name required"}, status_code=400)
            from client.plugins.manager import plugin_manager
            result = await plugin_manager.execute(plugin_name, action=action, **params)
            return JSONResponse(result)

        @app.get("/api/localai/status")
        async def local_ai_status():
            from client.local_ai import get_status
            return JSONResponse(get_status())

        @app.get("/api/ngrok")
        async def ngrok_info():
            try:
                async with httpx.AsyncClient(timeout=3.0) as c:
                    r = await c.get("http://localhost:4040/api/tunnels")
                    tunnels = r.json().get("tunnels", [])
                    for t in tunnels:
                        if t.get("proto") == "https":
                            return JSONResponse({"url": t["public_url"], "status": "active"})
            except Exception:
                pass
            return JSONResponse({"url": None, "status": "not running"})

        @app.post("/api/run")
        async def run_command(request: Request):
            body = await request.json()
            command = body.get("command", "")
            if not command:
                return JSONResponse({"error": "command required"}, status_code=400)
            try:
                import subprocess
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    timeout=60,
                    cwd=str(Path.cwd()),
                )
                return JSONResponse({
                    "result": proc.stdout.decode(errors="replace").strip(),
                    "error": proc.stderr.decode(errors="replace").strip(),
                    "returncode": proc.returncode,
                    "success": proc.returncode == 0,
                })
            except subprocess.TimeoutExpired:
                return JSONResponse({"result": "", "error": "Command timed out (60s)", "returncode": -1, "success": False})
            except Exception as e:
                return JSONResponse({"result": "", "error": str(e), "returncode": -1, "success": False})

    async def broadcast(self, message: dict[str, Any]) -> None:
        pass


def create_app() -> FastAPI:
    """Factory function for gunicorn."""
    config = ClientConfig.from_env()
    chat_client = ChatClient(config)
    file_manager = FileManager(config)
    ui = LocalUI(config, chat_client, file_manager)
    return ui.app
