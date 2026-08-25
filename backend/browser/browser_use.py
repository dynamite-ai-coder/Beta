from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_BROWSER_USE_AVAILABLE = False
try:
    from browser_use import Agent, Browser, BrowserConfig
    from langchain_core.language_models import BaseChatModel
    _BROWSER_USE_AVAILABLE = True
except ImportError:
    logger.info("browser-use not installed, using Selenium fallback")


class BrowserUseAdapter:
    def __init__(self, llm: Any = None) -> None:
        self._llm = llm
        self._browser: Any = None
        self._available = _BROWSER_USE_AVAILABLE

    @property
    def is_available(self) -> bool:
        return self._available

    async def start(self, headless: bool = True) -> bool:
        if not self._available:
            logger.warning("browser-use not available")
            return False
        try:
            config = BrowserConfig(headless=headless)
            self._browser = Browser(config=config)
            await self._browser.start()
            logger.info("browser-use browser started (headless=%s)", headless)
            return True
        except Exception as e:
            logger.error("browser-use start failed: %s", e)
            return False

    async def stop(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.debug("browser-use close error: %s", e)
            self._browser = None

    async def execute_task(
        self,
        task_description: str,
        target_url: str,
        credentials: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self._available or not self._browser:
            return {"success": False, "error": "browser-use not available"}

        if not self._llm:
            return {"success": False, "error": "No LLM configured for browser-use"}

        try:
            context = await self._browser.new_context()
            agent = Agent(
                task=task_description,
                llm=self._llm,
                browser=self._browser,
                browser_context=context,
            )
            result = await agent.run(max_steps=20)

            return {
                "success": True,
                "result": str(result) if result else "",
                "steps": len(result.history) if hasattr(result, "history") else 0,
            }
        except Exception as e:
            logger.error("browser-use task error: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            try:
                await context.close()
            except Exception:
                pass

    async def navigate(self, url: str) -> bool:
        if not self._browser:
            return False
        try:
            context = await self._browser.new_context()
            page = await context.get_current_page()
            await page.goto(url)
            return True
        except Exception as e:
            logger.error("browser-use navigate error: %s", e)
            return False

    async def take_screenshot(self) -> bytes | None:
        if not self._browser:
            return None
        try:
            context = await self._browser.new_context()
            page = await context.get_current_page()
            return await page.screenshot()
        except Exception as e:
            logger.error("browser-use screenshot error: %s", e)
            return None


class GroqLLMForBrowserUse:
    """Adapter to make Groq API work with browser-use's LangChain interface."""
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.groq.com/openai/v1") -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

    async def invoke(self, messages: list[dict]) -> Any:
        import httpx
        formatted = []
        for msg in messages:
            if hasattr(msg, "content"):
                formatted.append({"role": "user", "content": str(msg.content)})
            elif isinstance(msg, dict):
                formatted.append(msg)
            else:
                formatted.append({"role": "user", "content": str(msg)})

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": formatted,
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            class _Result:
                def __init__(self, text):
                    self.content = text
                def __str__(self):
                    return self.content

            return _Result(content)

    def bind_tools(self, tools: list) -> "GroqLLMForBrowserUse":
        return self
