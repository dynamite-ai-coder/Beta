from __future__ import annotations

import asyncio
import logging
import signal
import sys

from client.config import ClientConfig
from client.websocket_client import WebSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = ClientConfig.from_env()
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))

    logger.info(f"Starting Windows Browser Agent: {config.client_id}")
    logger.info(f"Backend: {config.backend_url}")

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
        logger.info("Agent stopped")


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
