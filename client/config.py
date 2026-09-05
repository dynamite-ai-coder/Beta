from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


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

    # Local Web UI
    local_ui_host: str = "127.0.0.1"
    local_ui_port: int = 23400

    # Browser preview
    browser_preview_enabled: bool = True
    browser_preview_fps: int = 2
    browser_preview_quality: int = 70
    browser_preview_max_width: int = 1024

    # File uploads
    max_upload_size: int = 10_485_760  # 10MB
    allowed_extensions: str = "txt,pdf,docx,csv,json,png,jpg,jpeg"

    # Browser engine
    browser_engine: str = "selenium"

    # API auth for backend
    api_token: str = ""

    # Local AI (optional preprocessor)
    local_ai_enabled: bool = False
    local_ai_model: str = ""
    local_ai_context: int = 2048
    local_ai_max_tokens: int = 256
    local_ai_threads: int = 2

    @classmethod
    def from_env(cls) -> ClientConfig:
        backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
        ws_url = backend_url.replace("https://", "wss://").replace("http://", "ws://")
        return cls(
            backend_url=backend_url,
            ws_url=ws_url,
            client_id=os.environ.get("CLIENT_ID", f"beta-client-{os.getpid()}"),
            client_token=os.environ.get("CLIENT_TOKEN", ""),
            api_token=os.environ.get("API_AUTH_TOKEN", ""),
            browser_headless=os.environ.get("BROWSER_HEADLESS", "true").lower() == "true",
            browser_profile_path=os.environ.get("BROWSER_PROFILE_PATH", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            task_timeout=int(os.environ.get("TASK_TIMEOUT", "300")),
            local_ui_host=os.environ.get("LOCAL_UI_HOST", "127.0.0.1"),
            local_ui_port=int(os.environ.get("LOCAL_UI_PORT", "23400")),
            browser_preview_enabled=os.environ.get("BROWSER_PREVIEW_ENABLED", "true").lower() == "true",
            browser_preview_fps=int(os.environ.get("BROWSER_PREVIEW_FPS", "2")),
            browser_preview_quality=int(os.environ.get("BROWSER_PREVIEW_QUALITY", "70")),
            browser_engine=os.environ.get("BROWSER_ENGINE", "selenium"),
            max_upload_size=int(os.environ.get("MAX_UPLOAD_SIZE", "10485760")),
            allowed_extensions=os.environ.get("ALLOWED_EXTENSIONS", "txt,pdf,docx,csv,json,png,jpg,jpeg"),
            local_ai_enabled=os.environ.get("LOCAL_AI_ENABLED", "false").lower() == "true",
            local_ai_model=os.environ.get("LOCAL_AI_MODEL", ""),
            local_ai_context=int(os.environ.get("LOCAL_AI_CONTEXT", "2048")),
            local_ai_max_tokens=int(os.environ.get("LOCAL_AI_MAX_TOKENS", "256")),
            local_ai_threads=int(os.environ.get("LOCAL_AI_THREADS", "2")),
        )
