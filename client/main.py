from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading

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

    local_ui = LocalUI(config, chat_client, file_manager)
    _start_local_ui(local_ui, config.local_ui_host, config.local_ui_port)

    print_status(f"Local Web UI: http://{config.local_ui_host}:{config.local_ui_port}")
    print_status("Client is ready. Open the URL above in your browser.")
    print_status("Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
