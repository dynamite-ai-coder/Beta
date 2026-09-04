from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time
from pathlib import Path
from typing import Any

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "screenshot"
    description = "Capture browser screenshots, save to file, compare pages"
    version = "1.0.0"
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
            "capture_full": self._capture_full,
            "save": self._save,
            "list": self._list_screenshots,
            "compare": self._compare,
            "capture_element": self._capture_element,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kwargs)

    async def _capture(self, name: str = "", quality: int = 80, **kw: Any) -> dict:
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}

        b64 = await self._browser_worker.take_screenshot()
        if not b64:
            return {"error": "Screenshot failed"}

        ts = int(time.time())
        filename = name or f"screen_{ts}"
        if not filename.endswith(".png"):
            filename += ".png"

        path = self._output_dir / filename
        img_bytes = base64.b64decode(b64)
        path.write_bytes(img_bytes)

        return {
            "path": str(path),
            "filename": filename,
            "size_bytes": len(img_bytes),
            "timestamp": ts,
            "preview": b64[:100] + "...",
        }

    async def _capture_full(self, name: str = "", **kw: Any) -> dict:
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}

        page_source = await self._browser_worker.get_page_source()
        current_url = await self._browser_worker.get_current_url()
        b64 = await self._browser_worker.take_screenshot()

        ts = int(time.time())
        filename = name or f"full_{ts}"
        if not filename.endswith(".png"):
            filename += ".png"

        result = {"url": current_url, "timestamp": ts}
        if b64:
            path = self._output_dir / filename
            img_bytes = base64.b64decode(b64)
            path.write_bytes(img_bytes)
            result["path"] = str(path)
            result["filename"] = filename
            result["size_bytes"] = len(img_bytes)

        if page_source:
            html_path = self._output_dir / f"{filename}.html"
            html_path.write_text(page_source[:50000], encoding="utf-8")
            result["html_path"] = str(html_path)

        return result

    async def _save(self, b64_data: str = "", name: str = "", **kw: Any) -> dict:
        if not b64_data:
            return {"error": "b64_data required"}

        ts = int(time.time())
        filename = name or f"saved_{ts}"
        if not filename.endswith(".png"):
            filename += ".png"

        path = self._output_dir / filename
        img_bytes = base64.b64decode(b64_data)
        path.write_bytes(img_bytes)

        return {"path": str(path), "filename": filename, "size_bytes": len(img_bytes)}

    async def _list_screenshots(self, limit: int = 20, **kw: Any) -> dict:
        files = sorted(self._output_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        items = []
        for f in files[:limit]:
            stat = f.stat()
            items.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
        return {"screenshots": items, "count": len(items), "dir": str(self._output_dir)}

    async def _compare(self, name_a: str = "", name_b: str = "", **kw: Any) -> dict:
        try:
            from PIL import Image
            import hashlib

            path_a = self._output_dir / name_a
            path_b = self._output_dir / name_b

            if not path_a.exists():
                return {"error": f"File not found: {name_a}"}
            if not path_b.exists():
                return {"error": f"File not found: {name_b}"}

            img_a = Image.open(path_a)
            img_b = Image.open(path_b)

            hash_a = hashlib.md5(img_a.tobytes()).hexdigest()
            hash_b = hashlib.md5(img_b.tobytes()).hexdigest()

            identical = hash_a == hash_b

            diff_info = {}
            if not identical and img_a.size == img_b.size:
                from PIL import ImageChops
                diff = ImageChops.difference(img_a, img_b)
                bbox = diff.getbbox()
                if bbox:
                    diff_info["diff_region"] = {"x": bbox[0], "y": bbox[1],
                                                 "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1]}
                    diff_info["diff_pixels"] = sum(1 for p in diff.getdata() if any(c > 0 for c in p[:3]))

            return {
                "identical": identical,
                "hash_a": hash_a, "hash_b": hash_b,
                "size_a": img_a.size, "size_b": img_b.size,
                **diff_info,
            }
        except ImportError:
            return {"error": "Pillow required for comparison"}

    async def _capture_element(self, selector: str = "", name: str = "", **kw: Any) -> dict:
        if not selector:
            return {"error": "selector required"}
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}

        try:
            from selenium.webdriver.common.by import By
            driver = self._browser_worker._driver
            element = driver.find_element(By.CSS_SELECTOR, selector)
            b64 = element.screenshot_as_base64

            ts = int(time.time())
            filename = name or f"element_{ts}"
            if not filename.endswith(".png"):
                filename += ".png"

            path = self._output_dir / filename
            path.write_bytes(base64.b64decode(b64))

            return {"path": str(path), "filename": filename, "selector": selector}
        except Exception as e:
            return {"error": str(e)}
