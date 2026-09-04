from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Optional

from client.config import ClientConfig

logger = logging.getLogger(__name__)


class BrowserPreview:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._last_screenshot: Optional[bytes] = None
        self._last_screenshot_time: float = 0
        self._min_interval = 1.0 / max(config.browser_preview_fps, 1)

    async def capture(self, browser_worker) -> Optional[str]:
        if not self._config.browser_preview_enabled:
            return None

        now = time.monotonic()
        if now - self._last_screenshot_time < self._min_interval:
            if self._last_screenshot:
                return base64.b64encode(self._last_screenshot).decode()
            return None

        try:
            screenshot = await browser_worker.take_screenshot()
            if screenshot:
                screenshot = self._compress_screenshot(screenshot)
                self._last_screenshot = screenshot
                self._last_screenshot_time = time.monotonic()
                return base64.b64encode(screenshot).decode()
        except Exception as e:
            logger.error(f"Screenshot capture error: {e}")
        return None

    def _compress_screenshot(self, data: bytes) -> bytes:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            max_w = self._config.browser_preview_max_width
            if img.width > max_w:
                ratio = max_w / img.width
                new_h = int(img.height * ratio)
                img = img.resize((max_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self._config.browser_preview_quality, optimize=True)
            return buf.getvalue()
        except ImportError:
            return data
        except Exception as e:
            logger.warning(f"Screenshot compression failed: {e}")
            return data

    @property
    def last_screenshot_b64(self) -> Optional[str]:
        if self._last_screenshot:
            return base64.b64encode(self._last_screenshot).decode()
        return None
