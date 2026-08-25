from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

JS_COLLECT_DOM = """
var MAX = arguments[0] || 80;
var selectors = {};
function addEl(el, sel) {
    if (!el || !sel || selectors[sel]) return;
    var tag = el.tagName ? el.tagName.toLowerCase() : '';
    if (['script','style','noscript','link','meta'].indexOf(tag) >= 0) return;
    selectors[sel] = {
        tag: tag, id: el.id || '', name: el.name || '',
        type: el.type || '', placeholder: el.placeholder || '',
        aria_label: el.getAttribute('aria-label') || '',
        text: (el.textContent || '').trim().substring(0, 100),
        role: el.getAttribute('role') || '',
        css_selector: sel
    };
}
function getSelector(el) {
    if (el.id) return '#' + el.id;
    if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
    var path = [];
    while (el && el.nodeType === 1) {
        var sel = el.tagName.toLowerCase();
        if (el.id) { path.unshift('#' + el.id); break; }
        if (el.className) sel += '.' + el.className.trim().split(/\\s+/).join('.');
        path.unshift(sel);
        el = el.parentElement;
    }
    return path.join(' > ');
}
document.querySelectorAll('input[type=text],input[type=email],input[type=tel],input[type=password],input:not([type]),button[type=submit],button,button[role=button],input[role=button],a[href]').forEach(function(el) {
    addEl(el, getSelector(el));
});
var result = [];
var keys = Object.keys(selectors);
for (var i = 0; i < Math.min(keys.length, MAX); i++) {
    result.push(selectors[keys[i]]);
}
return result;
"""


class BrowserWorker:
    def __init__(self, worker_id: str = "worker-1") -> None:
        self.worker_id = worker_id
        self._driver = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready and self._driver is not None

    async def start(self) -> bool:
        async with self._lock:
            try:
                return await asyncio.to_thread(self._start_sync)
            except Exception as e:
                logger.error(f"Browser start failed: {e}")
                self._ready = False
                return False

    def _start_sync(self) -> bool:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1280,720")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )

            self._driver = webdriver.Chrome(options=options)
            self._driver.set_page_load_timeout(30)
            self._driver.implicitly_wait(5)
            self._ready = True
            logger.info(f"Browser started for {self.worker_id}")
            return True
        except Exception as e:
            logger.error(f"Chrome init failed: {e}")
            self._ready = False
            return False

    async def stop(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._stop_sync)

    def _stop_sync(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
            self._ready = False

    async def restart(self) -> bool:
        await self.stop()
        return await self.start()

    async def navigate(self, url: str) -> bool:
        if not self.is_ready:
            return False
        try:
            await asyncio.to_thread(self._driver.get, url)

            def _wait_ready():
                try:
                    return self._driver.execute_script("return document.readyState") == "complete"
                except Exception:
                    return False

            for _ in range(15):
                if await asyncio.to_thread(_wait_ready):
                    break
                await asyncio.sleep(0.5)
            return True
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            return False

    async def get_dom_elements(self, max_elements: int = 80) -> list[dict]:
        if not self.is_ready:
            return []
        try:
            result = await asyncio.to_thread(
                self._driver.execute_script, JS_COLLECT_DOM, max_elements
            )
            return result if result else []
        except Exception as e:
            logger.error(f"DOM extraction failed: {e}")
            return []

    async def find_element_by_selector(self, selector: str):
        if not self.is_ready:
            return None
        try:
            from selenium.webdriver.common.by import By
            return await asyncio.to_thread(
                self._driver.find_element, By.CSS_SELECTOR, selector
            )
        except Exception:
            return None

    async def type_text(self, selector: str, text: str) -> bool:
        elem = await self.find_element_by_selector(selector)
        if not elem:
            return False
        try:
            await asyncio.to_thread(elem.clear)
            await asyncio.to_thread(elem.send_keys, text)
            return True
        except Exception as e:
            logger.error(f"Type failed for {selector}: {e}")
            return False

    async def click_element(self, selector: str) -> bool:
        elem = await self.find_element_by_selector(selector)
        if not elem:
            return False
        try:
            await asyncio.to_thread(elem.click)
            return True
        except Exception as e:
            logger.error(f"Click failed for {selector}: {e}")
            return False

    async def take_screenshot(self) -> bytes | None:
        if not self.is_ready:
            return None
        try:
            return await asyncio.to_thread(self._driver.get_screenshot_as_png)
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    async def get_current_url(self) -> str:
        if not self.is_ready:
            return ""
        try:
            return await asyncio.to_thread(
                lambda: self._driver.current_url
            )
        except Exception:
            return ""

    async def get_page_source(self) -> str:
        if not self.is_ready:
            return ""
        try:
            return await asyncio.to_thread(
                lambda: self._driver.page_source
            )
        except Exception:
            return ""

    async def detect_captcha(self) -> bool:
        source = await self.get_page_source()
        indicators = [
            "captcha", "recaptcha", "hcaptcha", "cf-challenge",
            "cloudflare", "g-recaptcha", "h-captcha",
            "verify you are human", "unusual traffic",
            "access denied", "blocked", "security check",
        ]
        source_lower = source.lower()
        return any(ind in source_lower for ind in indicators)


class BrowserWorkerManager:
    def __init__(self, max_workers: int = 1) -> None:
        self.max_workers = max_workers
        self._workers: dict[str, BrowserWorker] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}

    async def get_or_create_worker(self, worker_id: str = "worker-1") -> BrowserWorker:
        if worker_id not in self._workers:
            self._workers[worker_id] = BrowserWorker(worker_id)
        return self._workers[worker_id]

    async def start_worker(self, worker_id: str = "worker-1") -> bool:
        worker = await self.get_or_create_worker(worker_id)
        return await worker.start()

    async def stop_worker(self, worker_id: str) -> None:
        worker = self._workers.get(worker_id)
        if worker:
            await worker.stop()

    async def stop_all(self) -> None:
        for worker in self._workers.values():
            await worker.stop()
        self._workers.clear()

    def get_worker(self, worker_id: str) -> Optional[BrowserWorker]:
        return self._workers.get(worker_id)

    def get_ready_worker(self) -> Optional[BrowserWorker]:
        for w in self._workers.values():
            if w.is_ready:
                return w
        return None
