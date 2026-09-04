from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading
from urllib.parse import urlparse

import uvicorn

from client.config import ClientConfig
from client.ui import print_header, print_status, print_error
from client.websocket_client import WebSocketClient
from client.chat import ChatClient
from client.files.manager import FileManager
from client.browser_preview import BrowserPreview
from client.ui.app import LocalUI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _start_local_ui(
    ui: LocalUI,
    host: str,
    port: int,
) -> None:
    config = uvicorn.Config(
        ui.app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    logger.info(f"Local Web UI: http://{host}:{port}")


async def main() -> None:
    config = ClientConfig.from_env()
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))

    logger.info(f"Starting Beta Client: {config.client_id}")
    logger.info(f"Backend: {config.backend_url}")

    chat_client = ChatClient(config)
    file_manager = FileManager(config)
    browser_preview = BrowserPreview(config)

    local_ui = LocalUI(config, chat_client, file_manager)
    _start_local_ui(local_ui, config.local_ui_host, config.local_ui_port)

    print_status(f"Local Web UI: http://{config.local_ui_host}:{config.local_ui_port}")

    client = WebSocketClient(config, on_task=lambda m: None)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(client.disconnect()))
        except NotImplementedError:
            pass

    try:
        await client.connect()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await client.disconnect()
        logger.info("Client stopped")


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
