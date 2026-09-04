from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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
        self._setup_routes()

    @property
    def app(self) -> FastAPI:
        return self._app

    def set_browser_worker(self, worker: Any) -> None:
        self._browser_worker = worker

    def set_browser_preview(self, preview: Any) -> None:
        self._browser_preview = preview

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
