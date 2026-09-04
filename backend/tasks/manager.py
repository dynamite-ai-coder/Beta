from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.schemas import TaskState
from backend.tasks.repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._events: dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()
        self._browser = None

    async def _get_repo(self) -> tuple[TaskRepository, AsyncSession] | None:
        try:
            from backend.database import async_session
            session = async_session()
            return TaskRepository(session), session
        except Exception as e:
            logger.error("Failed to create DB session: %s", e)
            return None

    def _get_browser(self):
        if self._browser is None:
            try:
                from backend.browser.driver import create_browser
                self._browser = create_browser()
            except Exception as e:
                logger.error("Failed to create browser: %s", e)
                return None
        return self._browser

    async def create_task(
        self,
        task_id: str,
        target_url: str,
        username: str,
        password: str,
        instruction: str,
    ) -> dict:
        now = datetime.now(timezone.utc)
        task = {
            "task_id": task_id,
            "state": TaskState.QUEUED,
            "target_url": target_url,
            "username": username,
            "password": password,
            "instruction": instruction,
            "created_at": now,
            "updated_at": now,
            "result": None,
            "reason": None,
            "screenshot_path": None,
            "preview_token": None,
        }
        async with self._lock:
            self._tasks[task_id] = task
            self._events[task_id] = []

        result = await self._get_repo()
        if result:
            repo, session = result
            try:
                await repo.create_task(
                    task_id=task_id,
                    target_url=target_url,
                    username=username,
                    password=password,
                    instruction=instruction,
                )
                await repo.add_event(task_id, "created")
            except Exception as e:
                logger.error("Failed to persist task to DB: %s", e)
            finally:
                await session.close()

        return task

    def get_task(self, task_id: str) -> dict | None:
        task = self._tasks.get(task_id)
        if task:
            return {k: v for k, v in task.items() if k != "password"}
        return None

    def _get_task_internal(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def get_events(self, task_id: str) -> list[dict]:
        return self._events.get(task_id, [])

    async def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        reason: str | None = None,
    ) -> None:
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["state"] = state
                self._tasks[task_id]["updated_at"] = datetime.now(timezone.utc)
                if reason:
                    self._tasks[task_id]["reason"] = reason
                self._add_event(task_id, "state_change", state.value)

        result = await self._get_repo()
        if result:
            repo, session = result
            try:
                await repo.update_task_state(
                    task_id, state.value, reason=reason
                )
                await repo.add_event(task_id, "state_change", state.value)
            except Exception as e:
                logger.error("Failed to persist state change to DB: %s", e)
            finally:
                await session.close()

    def _add_event(self, task_id: str, event: str, data: str | None = None) -> None:
        if task_id in self._events:
            self._events[task_id].append({
                "event": event,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    async def _execute_browser_task(self, task_id: str) -> None:
        task = self._get_task_internal(task_id)
        if not task:
            return

        await self.update_task_state(task_id, TaskState.STARTING)
        self._add_event(task_id, "browser_starting")

        try:
            await asyncio.to_thread(self._ensure_browser)
            browser = self._get_browser()
            if not browser:
                await self.update_task_state(
                    task_id, TaskState.FAILURE, "Failed to start browser"
                )
                return

            await self.update_task_state(task_id, TaskState.RUNNING)
            self._add_event(task_id, "navigating", task["target_url"])

            await asyncio.to_thread(
                self._navigate_with_retry, browser, task["target_url"]
            )

            import time
            time.sleep(2)

            await asyncio.to_thread(self._fill_and_submit, browser, task)

            import time
            time.sleep(3)

            screenshot = await asyncio.to_thread(
                browser.get_screenshot_as_png
            )
            img_dir = settings.img_dir
            os.makedirs(img_dir, exist_ok=True)
            screenshot_path = os.path.join(img_dir, f"{task_id}.png")
            with open(screenshot_path, "wb") as f:
                f.write(screenshot)
            task["screenshot_path"] = screenshot_path

            current_url = browser.current_url
            page_source = browser.page_source

            has_captcha = await asyncio.to_thread(
                self._detect_captcha, page_source
            )

            if has_captcha:
                await self.update_task_state(
                    task_id, TaskState.WAITING_FOR_MANUAL_ACTION,
                    "CAPTCHA detected"
                )
                self._add_event(task_id, "captcha_detected")
            else:
                await self.update_task_state(task_id, TaskState.SUCCESS)
                self._add_event(task_id, "task_completed", "success")

            task["result"] = json.dumps({
                "current_url": current_url,
                "has_captcha": has_captcha,
                "screenshot": screenshot_path,
            })

        except Exception as e:
            logger.error("Browser task %s error: %s", task_id, e)
            await self.update_task_state(
                task_id, TaskState.FAILURE, str(e)
            )
            self._add_event(task_id, "error", str(e))
        finally:
            self.save_result(task_id)

    def _ensure_browser(self) -> None:
        if self._browser is None:
            from backend.browser.driver import create_browser
            self._browser = create_browser()

    def _navigate_with_retry(self, driver, url: str) -> None:
        from backend.browser.driver import navigate_safe
        navigate_safe(driver, url, timeout=30)

    def _fill_and_submit(self, driver, task: dict) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        username = task["username"]
        password = task["password"]

        try:
            username_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    'input[type="text"], input[type="email"], input[name="username"], input[name="email"], input[autocomplete="username"]'
                ))
            )
            username_field.clear()
            username_field.send_keys(username)

            password_field = driver.find_element(
                By.CSS_SELECTOR,
                'input[type="password"]'
            )
            password_field.clear()
            password_field.send_keys(password)

            submit = driver.find_element(
                By.CSS_SELECTOR,
                'button[type="submit"], input[type="submit"], button[name="submit"]'
            )
            submit.click()
        except Exception as e:
            logger.warning("Auto-fill failed: %s", e)

    def _detect_captcha(self, page_source: str) -> bool:
        indicators = [
            "captcha", "recaptcha", "hcaptcha", "cf-challenge",
            "verify you are human", "unusual traffic", "access denied",
            "security check", "cloudflare", "challenge-platform",
        ]
        source_lower = page_source.lower()
        return any(ind in source_lower for ind in indicators)

    async def execute_task(self, task_id: str) -> None:
        asyncio.create_task(self._execute_browser_task(task_id))

    async def stop_task(self, task_id: str) -> bool:
        task = self._get_task_internal(task_id)
        if task:
            await self.update_task_state(task_id, TaskState.STOPPED, "Stopped by user")
            self._add_event(task_id, "task_stopped")
            self.save_result(task_id)
            return True
        return False

    async def manual_action_continue(self, task_id: str) -> bool:
        task = self._get_task_internal(task_id)
        if task and task["state"] == TaskState.WAITING_FOR_MANUAL_ACTION:
            await self.update_task_state(
                task_id, TaskState.RUNNING, "Resumed after manual action"
            )
            self._add_event(task_id, "manual_action_resumed")
            return True
        return False

    async def cleanup_all(self) -> None:
        if self._browser:
            try:
                self._browser.quit()
            except Exception:
                pass
            self._browser = None

    def save_result(self, task_id: str) -> None:
        task = self._get_task_internal(task_id)
        if not task:
            return

        state = task["state"]
        state_val = state.value if isinstance(state, TaskState) else state
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_url": task["target_url"],
            "username": task["username"],
            "task_id": task_id,
            "state": state_val,
            "reason": task.get("reason"),
            "screenshot_path": task.get("screenshot_path"),
        }
        with open(settings.results_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
