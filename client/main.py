from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

import uvicorn

from client.config import ClientConfig
from client.ui import print_header, print_status
from client.chat import ChatClient
from client.files.manager import FileManager
from client.ui.app import LocalUI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_server: uvicorn.Server | None = None
_browser_worker: Any = None


def _signal_handler(sig, frame):
    global _server
    if _server:
        _server.should_exit = True


async def main() -> None:
    global _server, _browser_worker

    config = ClientConfig.from_env()
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))

    print_header()
    logger.info(f"Starting Beta Client: {config.client_id}")
    logger.info(f"Backend: {config.backend_url}")

    from client.plugins.manager import plugin_manager
    await plugin_manager.load_builtin(config)
    logger.info(f"Plugins loaded: {len(plugin_manager.plugins)}")

    from client.local_ai import detect_environment
    env = detect_environment()
    logger.info(f"Environment: {env['platform']} | RAM: {env['ram_mb']}MB | Model: {env['recommended_model']}")

    chat_client = ChatClient(config)
    file_manager = FileManager(config)

    from client.browser import BrowserWorker
    browser_worker = BrowserWorker(worker_id="client-main")
    _browser_worker = browser_worker

    local_ui = LocalUI(config, chat_client, file_manager)

    logger.info("Starting browser (Selenium/Chrome)...")
    browser_ok = await browser_worker.start()
    if browser_ok:
        logger.info("Browser started successfully")
        local_ui.set_browser_worker(browser_worker)
        screenshot_plugin = plugin_manager.get("screenshot")
        if screenshot_plugin:
            screenshot_plugin.set_browser(browser_worker)
            logger.info("Screenshot plugin connected to browser")
        browser_plugin = plugin_manager.get("browser")
        if browser_plugin:
            browser_plugin.set_browser(browser_worker)
            logger.info("Browser plugin connected to browser")
    else:
        logger.warning("Browser failed to start - screenshots will use fallback API")

    print_status(f"Local Web UI: http://{config.local_ui_host}:{config.local_ui_port}")
    print_status("Client is ready. Open the URL above in your browser.")
    print_status("Press Ctrl+C to stop.")

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    _server = uvicorn.Server(uvicorn.Config(
        local_ui.app,
        host=config.local_ui_host,
        port=config.local_ui_port,
        log_level="info",
        access_log=False,
    ))
    await _server.serve()

    if _browser_worker:
        logger.info("Stopping browser...")
        await _browser_worker.stop()
        logger.info("Browser stopped")


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
