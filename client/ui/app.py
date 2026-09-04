from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

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
        self._app = FastAPI(title="Beta Browser AI")
        self._ws_clients: list[WebSocket] = []
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

        static_dir = BASE_DIR / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def index():
            template = BASE_DIR / "templates" / "index.html"
            return HTMLResponse(content=template.read_text(encoding="utf-8"))

        @app.get("/api/status")
        async def status():
            browser_ok = self._browser_worker is not None and self._browser_worker.is_ready if self._browser_worker else False
            return {
                "browser_connected": browser_ok,
                "ai_connected": True,
                "task_status": "idle",
                "client_id": self._config.client_id,
            }

        @app.get("/api/chat/history")
        async def chat_history():
            return {"history": self._chat.history}

        @app.post("/api/chat/send")
        async def chat_send(request: Request):
            body = await request.json()
            message = body.get("message", "").strip()
            if not message:
                return JSONResponse(status_code=400, content={"error": "Empty message"})

            file_context = body.get("file_context", "")
            response = await self._chat.send_message(message, file_context)
            return {"response": response, "history": self._chat.history}

        @app.post("/api/chat/clear")
        async def chat_clear():
            self._chat.clear_history()
            return {"status": "cleared"}

        @app.post("/api/upload")
        async def upload_file(file: UploadFile = File(...)):
            content = await file.read()
            valid, msg = self._files.validate_file(file.filename or "unknown", len(content))
            if not valid:
                return JSONResponse(status_code=400, content={"error": msg})

            text = self._files.extract_text(file.filename or "unknown", content)
            info = self._files.get_file_info(file.filename or "unknown", len(content))
            return {
                "status": "ok",
                "file_info": info,
                "extracted_text": text,
            }

        @app.get("/api/browser/screenshot")
        async def browser_screenshot():
            if self._browser_preview and self._browser_worker:
                b64 = await self._browser_preview.capture(self._browser_worker)
                if b64:
                    return {"screenshot": b64, "timestamp": time.time()}
            return {"screenshot": None}

        @app.get("/api/browser/status")
        async def browser_status():
            if self._browser_worker:
                url = await self._browser_worker.get_current_url() if self._browser_worker.is_ready else ""
                return {
                    "connected": self._browser_worker.is_ready,
                    "current_url": url,
                    "engine": self._config.browser_engine,
                }
            return {"connected": False, "current_url": "", "engine": self._config.browser_engine}

        @app.post("/api/browser/navigate")
        async def browser_navigate(request: Request):
            body = await request.json()
            url = body.get("url", "")
            if not url:
                return JSONResponse(status_code=400, content={"error": "No URL"})
            if not self._browser_worker or not self._browser_worker.is_ready:
                return JSONResponse(status_code=503, content={"error": "Browser not ready"})
            ok = await self._browser_worker.navigate(url)
            return {"status": "ok" if ok else "failed"}

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
                        return {"tasks": tasks, "current_task_id": self._current_task_id}
                    return {"tasks": [], "error": f"Backend returned {resp.status_code}", "current_task_id": self._current_task_id}
            except Exception as e:
                logger.error(f"Preview tasks error: {e}")
                return {"tasks": [], "error": str(e), "current_task_id": self._current_task_id}

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
                        return resp.json()
                    return {"screenshot": None, "error": f"Backend returned {resp.status_code}"}
            except Exception as e:
                logger.error(f"Preview screenshot error: {e}")
                return {"screenshot": None, "error": str(e)}

        @app.get("/api/preview")
        async def preview_page():
            template = BASE_DIR / "templates" / "preview.html"
            if template.exists():
                return HTMLResponse(content=template.read_text(encoding="utf-8"))
            return HTMLResponse(content="<h1>Preview not available</h1>", status_code=404)

        @app.get("/preview", response_class=HTMLResponse)
        async def preview_alias():
            template = BASE_DIR / "templates" / "preview.html"
            if template.exists():
                return HTMLResponse(content=template.read_text(encoding="utf-8"))
            return HTMLResponse(content="<h1>Preview not available</h1>", status_code=404)

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
                            return {"task_id": tasks[0]["task_id"], "state": tasks[0]["state"]}
                    resp2 = await client.get(
                        f"{self._config.backend_url}/api/v1/tasks",
                        headers=headers,
                        params={"limit": 1},
                    )
                    if resp2.status_code == 200:
                        tasks2 = resp2.json()
                        if tasks2:
                            return {"task_id": tasks2[0]["task_id"], "state": tasks2[0]["state"]}
            except Exception as e:
                logger.error(f"Auto task error: {e}")
            return {"task_id": None, "state": None}

        @app.get("/api/preview/stream")
        async def preview_stream(task_id: str = "", fps: int = 15):
            if not task_id:
                return JSONResponse(status_code=400, content={"error": "task_id required"})

            fps = max(1, min(fps, 30))
            interval = 1.0 / fps

            async def mjpeg_generator():
                headers = {}
                if self._config.api_token:
                    headers["Authorization"] = f"Bearer {self._config.api_token}"

                async with httpx.AsyncClient(timeout=5.0) as client:
                    while True:
                        try:
                            resp = await client.get(
                                f"{self._config.backend_url}/v1/browser/screenshot/{task_id}",
                                headers=headers,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                b64 = data.get("screenshot")
                                if b64:
                                    jpeg_bytes = base64.b64decode(b64)
                                    if _HAS_PIL:
                                        try:
                                            img = Image.open(io.BytesIO(jpeg_bytes))
                                            img = img.resize((320, 240), Image.LANCZOS)
                                            buf = io.BytesIO()
                                            img.save(buf, format="JPEG", quality=75, optimize=True)
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
                mjpeg_generator(),
                media_type="multipart/x-mixed-replace; boundary=frame",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.get("/api/plugins")
        async def list_plugins():
            from client.plugins.manager import plugin_manager
            return {"plugins": plugin_manager.list_all()}

        @app.post("/api/plugins/execute")
        async def execute_plugin(request: Request):
            body = await request.json()
            plugin_name = body.get("name", "")
            action = body.get("action", "")
            params = body.get("params", {})
            if not plugin_name:
                return JSONResponse(status_code=400, content={"error": "Plugin name required"})
            from client.plugins.manager import plugin_manager
            result = await plugin_manager.execute(plugin_name, action=action, **params)
            return result

        @app.get("/api/localai/status")
        async def local_ai_status():
            from client.local_ai import get_status
            return get_status()

        @app.post("/api/run")
        async def run_command(request: Request):
            import shlex
            import sys as _sys
            body = await request.json()
            command = body.get("command", "")
            if not command:
                return JSONResponse(status_code=400, content={"error": "command required"})
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(Path.cwd()),
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
                return {
                    "result": stdout.decode(errors="replace").strip(),
                    "error": stderr.decode(errors="replace").strip(),
                    "returncode": proc.returncode,
                    "success": proc.returncode == 0,
                }
            except asyncio.TimeoutError:
                return {"result": "", "error": "Command timed out (60s)", "returncode": -1, "success": False}
            except Exception as e:
                return {"result": "", "error": str(e), "returncode": -1, "success": False}

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self._ws_clients.append(websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    elif msg.get("type") == "chat":
                        message = msg.get("message", "")
                        if message:
                            response = await self._chat.send_message(message)
                            await websocket.send_text(json.dumps({
                                "type": "chat_response",
                                "response": response,
                            }))
            except WebSocketDisconnect:
                self._ws_clients.remove(websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if websocket in self._ws_clients:
                    self._ws_clients.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in self._ws_clients:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.remove(ws)
