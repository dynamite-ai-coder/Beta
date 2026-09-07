from __future__ import annotations

import base64
import logging
import time
from typing import Any

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "browser"
    description = "Browser automation via Selenium: navigate, click, type, screenshot, DOM extraction"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._browser_worker = None

    def set_browser(self, worker: Any) -> None:
        self._browser_worker = worker

    async def execute(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        actions = {
            "status": self._status,
            "navigate": self._navigate,
            "click": self._click,
            "type": self._type,
            "screenshot": self._screenshot,
            "dom": self._dom,
            "get_url": self._get_url,
            "get_source": self._get_source,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kwargs)

    async def _status(self, **kw: Any) -> dict:
        if not self._browser_worker:
            return {"connected": False, "error": "Browser worker not initialized"}
        return {
            "connected": self._browser_worker.is_ready,
            "engine": "selenium",
            "current_url": await self._browser_worker.get_current_url() if self._browser_worker.is_ready else "",
        }

    async def _navigate(self, url: str = "", **kw: Any) -> dict:
        if not url:
            return {"error": "url required"}
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}
        ok = await self._browser_worker.navigate(url)
        if ok:
            await asyncio.sleep(1)
            current = await self._browser_worker.get_current_url()
            return {"status": "ok", "url": current}
        return {"status": "failed"}

    async def _click(self, selector: str = "", **kw: Any) -> dict:
        if not selector:
            return {"error": "selector required"}
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}
        ok = await self._browser_worker.click_element(selector)
        return {"status": "ok" if ok else "failed", "selector": selector}

    async def _type(self, selector: str = "", text: str = "", **kw: Any) -> dict:
        if not selector or not text:
            return {"error": "selector and text required"}
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}
        ok = await self._browser_worker.type_text(selector, text)
        return {"status": "ok" if ok else "failed", "selector": selector}

    async def _screenshot(self, **kw: Any) -> dict:
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}
        png_bytes = await self._browser_worker.take_screenshot()
        if png_bytes:
            b64 = base64.b64encode(png_bytes).decode()
            return {"screenshot": b64, "size_bytes": len(png_bytes)}
        return {"error": "Screenshot failed"}

    async def _dom(self, max_elements: int = 80, **kw: Any) -> dict:
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}
        elements = await self._browser_worker.get_dom_elements(max_elements)
        url = await self._browser_worker.get_current_url()
        return {"elements": elements, "url": url, "count": len(elements)}

    async def _get_url(self, **kw: Any) -> dict:
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}
        url = await self._browser_worker.get_current_url()
        return {"url": url}

    async def _get_source(self, **kw: Any) -> dict:
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}
        source = await self._browser_worker.get_page_source()
        return {"source": source[:5000], "length": len(source)}


import asyncio
