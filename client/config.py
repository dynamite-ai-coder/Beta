from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ClientConfig:
    backend_url: str = "http://localhost:8000"
    ws_url: str = "ws://localhost:8000"
    client_id: str = ""
    client_token: str = ""
    browser_headless: bool = True
    browser_profile_path: str = ""
    log_level: str = "INFO"
    reconnect_delay_start: float = 1.0
    reconnect_delay_max: float = 30.0
    heartbeat_interval: float = 25.0
    task_timeout: int = 300

    @classmethod
    def from_env(cls) -> ClientConfig:
        backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
        ws_url = backend_url.replace("https://", "wss://").replace("http://", "ws://")
        return cls(
            backend_url=backend_url,
            ws_url=ws_url,
            client_id=os.environ.get("CLIENT_ID", f"windows-client-{os.getpid()}"),
            client_token=os.environ.get("CLIENT_TOKEN", ""),
            browser_headless=os.environ.get("BROWSER_HEADLESS", "true").lower() == "true",
            browser_profile_path=os.environ.get("BROWSER_PROFILE_PATH", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            task_timeout=int(os.environ.get("TASK_TIMEOUT", "300")),
        )
