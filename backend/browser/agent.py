from __future__ import annotations

import logging

from backend.ai.identifier import ElementIdentifier
from backend.browser.driver import (
    collect_dom_elements,
    create_browser,
    detect_captcha,
    navigate_safe,
    take_screenshot,
)
from backend.models.schemas import AISelectors, TaskState

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """You are a browser automation agent for authorized testing.

You can perform these actions:
- navigate: Go to a URL. Requires "url" field.
- click: Click an element. Requires "selector" field.
- type: Type text into a field. Requires "selector" and "value" fields.
- wait: Wait for conditions.
- inspect: Examine the page.
- screenshot: Take a screenshot.
- finish: Task complete.
- request_manual_action: Request human intervention. Requires "reason" field.

Rules:
- Use minimum number of actions
- Prefer stable selectors (id, name)
- Never expose credentials in actions
- Request manual action for CAPTCHAs
- Stop when login succeeds or clearly fails
- Respond ONLY with valid JSON: {"action": "...", "selector": "...", "value": "...", "url": "...", "reason": "..."}
"""


class BrowserAgent:
    def __init__(self, task_id: str, ai_identifier: ElementIdentifier) -> None:
        self.task_id = task_id
        self._ai = ai_identifier
        self._driver = None
        self._state = TaskState.QUEUED
        self._history: list[dict] = []
        self._max_steps = 20
        self._step = 0

    @property
    def state(self) -> TaskState:
        return self._state

    @state.setter
    def state(self, value: TaskState) -> None:
        self._state = value

    def start_browser(self) -> None:
        self._driver = create_browser()
        self._state = TaskState.STARTING

    def close_browser(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    async def execute_login(
        self,
        target_url: str,
        username: str,
        password: str,
        instruction: str,
    ) -> dict:
        if not self._driver:
            self.start_browser()

        self._state = TaskState.RUNNING
        result = {
            "task_id": self.task_id,
            "state": TaskState.FAILURE,
            "result": None,
            "reason": None,
            "screenshot_path": None,
        }

        try:
            if not navigate_safe(self._driver, target_url):
                result["reason"] = "Failed to navigate to target URL"
                return result

            if detect_captcha(self._driver):
                self._state = TaskState.WAITING_FOR_MANUAL_ACTION
                result["state"] = TaskState.WAITING_FOR_MANUAL_ACTION
                result["reason"] = "CAPTCHA or anti-bot protection detected. Manual action required."
                return result

            selectors = await self._ai.identify_elements(
                [type(e).__module__ == "__main__" and e or e for e in self._extract_elements()]
            )

            if not selectors:
                result["reason"] = "AI could not identify page elements"
                return result

            filled = await self._fill_and_submit(selectors, username, password)
            if not filled:
                result["reason"] = "Failed to fill or submit login form"
                return result

            self._driver.implicitly_wait(3)
            import time
            time.sleep(2)

            if detect_captcha(self._driver):
                self._state = TaskState.WAITING_FOR_MANUAL_ACTION
                result["state"] = TaskState.WAITING_FOR_MANUAL_ACTION
                result["reason"] = "CAPTCHA detected after login attempt"
                return result

            if self._detect_login_success():
                self._state = TaskState.SUCCESS
                result["state"] = TaskState.SUCCESS
                result["result"] = "Login successful"
                result["reason"] = "Successfully authenticated"
            else:
                self._state = TaskState.FAILURE
                result["state"] = TaskState.FAILURE
                result["reason"] = "Login failed - could not confirm success"

        except Exception as e:
            logger.error("Login execution failed: %s", e)
            self._state = TaskState.FAILURE
            result["reason"] = f"Error: {e!s}"

        return result

    def _extract_elements(self) -> list:
        raw = collect_dom_elements(self._driver)
        from backend.models.schemas import DOMElement
        return [DOMElement(**el) for el in raw]

    async def _fill_and_submit(
        self, selectors: AISelectors, username: str, password: str
    ) -> bool:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            wait = WebDriverWait(self._driver, 10)

            user_field = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, selectors.username_selector)
            ))
            user_field.clear()
            user_field.send_keys(username)

            pass_field = self._driver.find_element(
                By.CSS_SELECTOR, selectors.password_selector
            )
            pass_field.clear()
            pass_field.send_keys(password)

            submit_btn = self._driver.find_element(
                By.CSS_SELECTOR, selectors.submit_selector
            )
            submit_btn.click()

            return True
        except Exception as e:
            logger.error("Fill and submit failed: %s", e)
            return False

    def _detect_login_success(self) -> bool:
        current_url = self._driver.current_url.lower()
        page_source = self._driver.page_source.lower()

        success_indicators = [
            "dashboard", "welcome", "home", "account", "profile",
            "logout", "sign out", "settings", "my-account",
        ]
        failure_indicators = [
            "invalid", "incorrect", "failed", "error", "wrong",
            "unauthorized", "denied", "try again",
        ]

        for ind in success_indicators:
            if ind in current_url or ind in page_source:
                return True

        for ind in failure_indicators:
            if ind in page_source:
                return False

        return False

    def take_screenshot(self) -> bytes | None:
        if self._driver:
            return take_screenshot(self._driver)
        return None
