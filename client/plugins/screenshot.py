from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)

THUM_IO_API = "https://image.thum.io/get/width/1280/crop/720/"


class Plugin(PluginBase):
    name = "screenshot"
    description = "Capture browser screenshots via API or selenium"
    version = "1.1.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._output_dir = Path(os.environ.get("SCREENSHOT_DIR", "./screenshots"))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._browser_worker = None

    def set_browser(self, worker: Any) -> None:
        self._browser_worker = worker

    async def execute(self, action: str = "capture", **kwargs: Any) -> dict[str, Any]:
        actions = {
            "capture": self._capture,
            "capture_url": self._capture_url,
            "save": self._save,
            "list": self._list_screenshots,
            "compare": self._compare,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kwargs)

    async def _capture(self, url: str = "", name: str = "", width: int = 1280, height: int = 720, **kw: Any) -> dict:
        if not url:
            return {"error": "url required"}

        if self._browser_worker and self._browser_worker.is_ready:
            try:
                b64 = await self._browser_worker.take_screenshot()
                if b64:
                    ts = int(time.time())
                    filename = name or f"screen_{ts}.png"
                    path = self._output_dir / filename
                    path.write_bytes(base64.b64decode(b64))
                    return {"screenshot": b64, "path": str(path), "filename": filename, "source": "selenium"}
            except Exception as e:
                logger.warning(f"Selenium screenshot failed, using API: {e}")

        return await self._capture_url(url=url, name=name, width=width, height=height, **kw)

    async def _capture_url(self, url: str = "", name: str = "", width: int = 1280, height: int = 720, **kw: Any) -> dict:
        if not url:
            return {"error": "url required"}

        api_url = f"https://image.thum.io/get/width/{width}/crop/{height}/{url}"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(api_url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    b64 = base64.b64encode(resp.content).decode()
                    ts = int(time.time())
                    filename = name or f"screen_{ts}.png"
                    path = self._output_dir / filename
                    path.write_bytes(resp.content)
                    return {
                        "screenshot": b64,
                        "path": str(path),
                        "filename": filename,
                        "size_bytes": len(resp.content),
                        "url": url,
                        "source": "thum.io",
                    }
                return {"error": f"Screenshot API returned {resp.status_code}", "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}

    async def _save(self, b64_data: str = "", name: str = "", **kw: Any) -> dict:
        if not b64_data:
            return {"error": "b64_data required"}
        ts = int(time.time())
        filename = name or f"saved_{ts}.png"
        path = self._output_dir / filename
        path.write_bytes(base64.b64decode(b64_data))
        return {"path": str(path), "filename": filename, "size_bytes": path.stat().st_size}

    async def _list_screenshots(self, limit: int = 20, **kw: Any) -> dict:
        files = sorted(self._output_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        items = [{"filename": f.name, "size_bytes": f.stat().st_size} for f in files[:limit]]
        return {"screenshots": items, "count": len(items)}

    async def _compare(self, name_a: str = "", name_b: str = "", **kw: Any) -> dict:
        try:
            import hashlib
            path_a = self._output_dir / name_a
            path_b = self._output_dir / name_b
            if not path_a.exists():
                return {"error": f"File not found: {name_a}"}
            if not path_b.exists():
                return {"error": f"File not found: {name_b}"}
            hash_a = hashlib.md5(path_a.read_bytes()).hexdigest()
            hash_b = hashlib.md5(path_b.read_bytes()).hexdigest()
            return {"identical": hash_a == hash_b, "hash_a": hash_a, "hash_b": hash_b}
        except Exception as e:
            return {"error": str(e)}
