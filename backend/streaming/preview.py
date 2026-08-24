from __future__ import annotations

import asyncio
import logging

from selenium.common.exceptions import WebDriverException

from backend.browser.driver import take_screenshot

logger = logging.getLogger(__name__)


class PreviewStreamer:
    def __init__(self) -> None:
        self._streams: dict[str, dict] = {}

    async def start_stream(self, task_id: str, token: str) -> str:
        if task_id not in self._streams:
            self._streams[task_id] = {
                "token": token,
                "frames": asyncio.Queue(maxsize=10),
                "active": True,
            }
        return f"/task/{task_id}/preview/stream?token={token}"

    def stop_stream(self, task_id: str) -> None:
        if task_id in self._streams:
            self._streams[task_id]["active"] = False

    async def generate_mjpeg(self, task_id: str):
        stream_info = self._streams.get(task_id)
        if not stream_info:
            return

        boundary = b"--frame\r\n"
        content_type = b"Content-Type: image/jpeg\r\n\r\n"

        while stream_info["active"]:
            try:
                frame = await asyncio.wait_for(stream_info["frames"].get(), timeout=1.0)
                yield boundary + content_type + frame + b"\r\n"
            except asyncio.TimeoutError:
                continue
            except StopAsyncIteration:
                break

    async def capture_frames(self, task_id: str, driver_factory=None):
        stream_info = self._streams.get(task_id)
        if not stream_info:
            return

        driver = None
        try:
            if driver_factory:
                driver = driver_factory()
            while stream_info["active"] and driver:
                frame = take_screenshot(driver)
                if frame:
                    try:
                        stream_info["frames"].put_nowait(frame)
                    except asyncio.QueueFull:
                        try:
                            stream_info["frames"].get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        stream_info["frames"].put_nowait(frame)
                await asyncio.sleep(0.5)
        except (WebDriverException, OSError, RuntimeError) as e:
            logger.error("Frame capture error: %s", e)
        finally:
            if driver:
                try:
                    driver.quit()
                except (WebDriverException, OSError) as e:
                    logger.debug("Preview driver close error (ignored): %s", e)

    def get_preview_url(self, task_id: str, base_url: str = "") -> str:
        stream_info = self._streams.get(task_id)
        if stream_info:
            return f"{base_url}/task/{task_id}/preview"
        return ""


preview_streamer = PreviewStreamer()
