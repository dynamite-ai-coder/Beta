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
from flask import Flask, Response, jsonify, request, send_from_directory

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
        self._app = Flask("Beta Browser AI")
        self._ws_clients: list = []
        self._browser_worker = None
        self._browser_preview = None
        self._current_task_id: Optional[str] = None
        self._current_preview_token: Optional[str] = None
        self._setup_routes()

    @property
    def app(self) -> Flask:
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

        @app.route("/")
        def index():
            template = BASE_DIR / "templates" / "index.html"
            return template.read_text(encoding="utf-8")

        @app.route("/api/status")
        def status():
            browser_ok = self._browser_worker is not None and self._browser_worker.is_ready if self._browser_worker else False
            ngrok_url = None
            try:
                with httpx.Client(timeout=3.0) as c:
                    r = c.get("http://localhost:4040/api/tunnels")
                    tunnels = r.json().get("tunnels", [])
                    for t in tunnels:
                        if t.get("proto") == "https":
                            ngrok_url = t.get("public_url")
                            break
            except Exception:
                pass
            return jsonify({
                "browser_connected": browser_ok,
                "ai_connected": True,
                "task_status": "idle",
                "client_id": self._config.client_id,
                "ngrok_url": ngrok_url,
            })

        @app.route("/api/chat/history")
        def chat_history():
            return jsonify({"history": self._chat.history})

        @app.route("/api/chat/send", methods=["POST"])
        def chat_send():
            body = request.get_json(force=True)
            message = body.get("message", "").strip()
            if not message:
                return jsonify({"error": "Empty message"}), 400

            file_context = body.get("file_context", "")
            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(
                    self._chat.send_message(message, file_context)
                )
            finally:
                loop.close()
            return jsonify({"response": response, "history": self._chat.history})

        @app.route("/api/chat/clear", methods=["POST"])
        def chat_clear():
            self._chat.clear_history()
            return jsonify({"status": "cleared"})

        @app.route("/api/tor/toggle", methods=["POST"])
        def tor_toggle():
            body = request.get_json(force=True) if request.data else {}
            enabled = body.get("enabled", False)
            try:
                backend_url = os.environ.get("BACKEND_URL", "https://beta-fmp9.onrender.com")
                token = os.environ.get("API_AUTH_TOKEN", "")
                with httpx.Client(timeout=10) as client:
                    r = client.post(
                        f"{backend_url}/api/tor/toggle",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"enabled": enabled},
                    )
                    if r.status_code == 200:
                        return jsonify({"status": "ok", "tor_enabled": enabled})
            except Exception:
                pass
            return jsonify({"status": "ok", "tor_enabled": enabled, "note": "local only"})

        @app.route("/api/upload", methods=["POST"])
        def upload_file():
            if "file" not in request.files:
                return jsonify({"error": "No file"}), 400
            f = request.files["file"]
            content = f.read()
            valid, msg = self._files.validate_file(f.filename or "unknown", len(content))
            if not valid:
                return jsonify({"error": msg}), 400

            text = self._files.extract_text(f.filename or "unknown", content)
            info = self._files.get_file_info(f.filename or "unknown", len(content))
            return jsonify({
                "status": "ok",
                "file_info": info,
                "extracted_text": text,
            })

        @app.route("/api/browser/screenshot")
        def browser_screenshot():
            if self._browser_preview and self._browser_worker:
                loop = asyncio.new_event_loop()
                try:
                    b64 = loop.run_until_complete(
                        self._browser_preview.capture(self._browser_worker)
                    )
                finally:
                    loop.close()
                if b64:
                    return jsonify({"screenshot": b64, "timestamp": time.time()})
            return jsonify({"screenshot": None})

        @app.route("/api/browser/status")
        def browser_status():
            if self._browser_worker:
                loop = asyncio.new_event_loop()
                try:
                    url = loop.run_until_complete(
                        self._browser_worker.get_current_url()
                    ) if self._browser_worker.is_ready else ""
                finally:
                    loop.close()
                return jsonify({
                    "connected": self._browser_worker.is_ready,
                    "current_url": url,
                    "engine": self._config.browser_engine,
                })
            return jsonify({"connected": False, "current_url": "", "engine": self._config.browser_engine})

        @app.route("/api/browser/navigate", methods=["POST"])
        def browser_navigate():
            body = request.get_json(force=True)
            url = body.get("url", "")
            if not url:
                return jsonify({"error": "No URL"}), 400
            if not self._browser_worker or not self._browser_worker.is_ready:
                return jsonify({"error": "Browser not ready"}), 503
            loop = asyncio.new_event_loop()
            try:
                ok = loop.run_until_complete(self._browser_worker.navigate(url))
            finally:
                loop.close()
            return jsonify({"status": "ok" if ok else "failed"})

        @app.route("/api/preview/tasks")
        def preview_tasks():
            try:
                headers = {}
                if self._config.api_token:
                    headers["Authorization"] = f"Bearer {self._config.api_token}"
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(
                        f"{self._config.backend_url}/api/v1/tasks",
                        headers=headers,
                        params={"limit": 5},
                    )
                    if resp.status_code == 200:
                        tasks = resp.json()
                        return jsonify({"tasks": tasks, "current_task_id": self._current_task_id})
                    return jsonify({"tasks": [], "error": f"Backend returned {resp.status_code}", "current_task_id": self._current_task_id})
            except Exception as e:
                logger.error(f"Preview tasks error: {e}")
                return jsonify({"tasks": [], "error": str(e), "current_task_id": self._current_task_id})

        @app.route("/api/preview/screenshot/<task_id>")
        def preview_screenshot(task_id):
            try:
                headers = {}
                if self._config.api_token:
                    headers["Authorization"] = f"Bearer {self._config.api_token}"
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(
                        f"{self._config.backend_url}/v1/browser/screenshot/{task_id}",
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        return jsonify(resp.json())
                    return jsonify({"screenshot": None, "error": f"Backend returned {resp.status_code}"})
            except Exception as e:
                logger.error(f"Preview screenshot error: {e}")
                return jsonify({"screenshot": None, "error": str(e)})

        @app.route("/api/preview")
        @app.route("/preview")
        def preview_page():
            template = BASE_DIR / "templates" / "preview.html"
            if template.exists():
                return template.read_text(encoding="utf-8")
            return "<h1>Preview not available</h1>", 404

        @app.route("/api/preview/auto_task")
        def preview_auto_task():
            try:
                headers = {}
                if self._config.api_token:
                    headers["Authorization"] = f"Bearer {self._config.api_token}"
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(
                        f"{self._config.backend_url}/api/v1/tasks",
                        headers=headers,
                        params={"limit": 1, "state": "running"},
                    )
                    if resp.status_code == 200:
                        tasks = resp.json()
                        if tasks:
                            return jsonify({"task_id": tasks[0]["task_id"], "state": tasks[0]["state"]})
                    resp2 = client.get(
                        f"{self._config.backend_url}/api/v1/tasks",
                        headers=headers,
                        params={"limit": 1},
                    )
                    if resp2.status_code == 200:
                        tasks2 = resp2.json()
                        if tasks2:
                            return jsonify({"task_id": tasks2[0]["task_id"], "state": tasks2[0]["state"]})
            except Exception as e:
                logger.error(f"Auto task error: {e}")
            return jsonify({"task_id": None, "state": None})

        @app.route("/api/preview/stream")
        def preview_stream():
            url = request.args.get("url", "https://example.com")
            fps = max(1, min(int(request.args.get("fps", 15)), 30))
            interval = 1.0 / fps

            def generate():
                from client.plugins.manager import plugin_manager
                screenshot_plugin = plugin_manager.get("screenshot")

                while True:
                    try:
                        if screenshot_plugin:
                            loop = asyncio.new_event_loop()
                            try:
                                result = loop.run_until_complete(
                                    screenshot_plugin.execute(action="capture", url=url, width=320, height=220)
                                )
                            finally:
                                loop.close()
                            b64 = result.get("screenshot", "")
                            if b64:
                                jpeg_bytes = base64.b64decode(b64)
                                if _HAS_PIL:
                                    try:
                                        img = Image.open(io.BytesIO(jpeg_bytes))
                                        img = img.resize((320, 220), Image.LANCZOS)
                                        buf = io.BytesIO()
                                        img.save(buf, format="JPEG", quality=70, optimize=True)
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

                    time.sleep(interval)

            return Response(
                generate(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.route("/api/plugins")
        def list_plugins():
            from client.plugins.manager import plugin_manager
            return jsonify({"plugins": plugin_manager.list_all()})

        @app.route("/api/plugins/execute", methods=["POST"])
        def execute_plugin():
            body = request.get_json(force=True)
            plugin_name = body.get("name", "")
            action = body.get("action", "")
            params = body.get("params", {})
            if not plugin_name:
                return jsonify({"error": "Plugin name required"}), 400
            from client.plugins.manager import plugin_manager
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    plugin_manager.execute(plugin_name, action=action, **params)
                )
            finally:
                loop.close()
            return jsonify(result)

        @app.route("/api/localai/status")
        def local_ai_status():
            from client.local_ai import get_status
            return jsonify(get_status())

        @app.route("/api/ngrok")
        def ngrok_info():
            try:
                with httpx.Client(timeout=3.0) as c:
                    r = c.get("http://localhost:4040/api/tunnels")
                    tunnels = r.json().get("tunnels", [])
                    for t in tunnels:
                        if t.get("proto") == "https":
                            return jsonify({"url": t["public_url"], "status": "active"})
            except Exception:
                pass
            return jsonify({"url": None, "status": "not running"})

        @app.route("/api/run", methods=["POST"])
        def run_command():
            body = request.get_json(force=True)
            command = body.get("command", "")
            if not command:
                return jsonify({"error": "command required"}), 400
            try:
                import subprocess
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    timeout=60,
                    cwd=str(Path.cwd()),
                )
                return jsonify({
                    "result": proc.stdout.decode(errors="replace").strip(),
                    "error": proc.stderr.decode(errors="replace").strip(),
                    "returncode": proc.returncode,
                    "success": proc.returncode == 0,
                })
            except subprocess.TimeoutExpired:
                return jsonify({"result": "", "error": "Command timed out (60s)", "returncode": -1, "success": False})
            except Exception as e:
                return jsonify({"result": "", "error": str(e), "returncode": -1, "success": False})

    async def broadcast(self, message: dict[str, Any]) -> None:
        pass
