from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API
    api_auth_token: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # AI / Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # Security
    allowed_domains: str = ""
    max_task_duration: int = 300
    task_timeout: int = 300
    browser_session_timeout: int = 600
    max_request_size: int = 10_485_760
    rate_limit_per_minute: int = 30

    # Browser
    browser_executable: str | None = None
    headless: bool = True

    # Preview
    preview_enabled: bool = True
    preview_token_secret: str = "change-me-in-production"

    # App
    debug: bool = False
    img_dir: str = "img"
    results_file: str = "results.jsonl"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "allow"}

    @property
    def allowed_domains_list(self) -> list[str]:
        if not self.allowed_domains:
            return []
        return [d.strip().lower() for d in self.allowed_domains.split(",") if d.strip()]


BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"}

settings = Settings()

logger = logging.getLogger(__name__)


def is_url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    if hostname.lower() in BLOCKED_HOSTS:
        return False

    try:
        ip = ipaddress.ip_address(hostname)
        for net in BLOCKED_NETWORKS:
            if ip in net:
                return False
    except ValueError:
        pass

    allowed = settings.allowed_domains_list
    if allowed:
        for domain in allowed:
            if hostname.lower() == domain.lower() or hostname.lower().endswith("." + domain.lower()):
                return True
        return False

    return True
