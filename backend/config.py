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

    # AI
    ai_api_key: str = ""
    ai_model: str = "llama-3.1-8b-instant"
    ai_base_url: str = "https://api.groq.com/openai/v1"
    ai_provider: str = "groq"

    # Database
    database_url: str = (
        "sqlite+aiosqlite:///./browser_automation.db"
    )

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

    # Proxy (Proxy-Cheap)
    proxy_enabled: bool = True
    proxy_secret: str = ""
    proxy_apikey: str = ""
    proxy_url: str = "http://01a03626-786e-79a1-9d39-8d77a7fcf978:01a03626-786e-79a1-9d39-8d77a8bb0953@proxy-us.proxy-cheap.com:5959"

    # Preview
    preview_enabled: bool = True
    preview_token_secret: str = "change-me-in-production"

    # App
    debug: bool = False
    img_dir: str = "img"
    results_file: str = "results.jsonl"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "allow",
    }

    def model_post_init(self, __context: object) -> None:
        import os
        self.api_auth_token = self.api_auth_token.strip()
        self.ai_api_key = self.ai_api_key.strip()
        self.ai_model = self.ai_model.strip()
        self.ai_base_url = self.ai_base_url.strip()
        self.database_url = self.database_url.strip()
        self.proxy_secret = self.proxy_secret.strip()
        self.proxy_apikey = self.proxy_apikey.strip()
        self.proxy_url = self.proxy_url.strip()
        if not self.proxy_secret:
            self.proxy_secret = os.environ.get(
                "PROXY_SECRET", os.environ.get("MOKE_SECRET", "")
            )
        if not self.proxy_apikey:
            self.proxy_apikey = os.environ.get(
                "PROXY_APIKEY", os.environ.get("MOKE_APIKEY", "")
            )
        if self.proxy_secret and self.proxy_apikey and not self.proxy_url:
            self.proxy_url = (
                f"http://{self.proxy_apikey}"
                f":{self.proxy_secret}"
                f"@proxy-us.proxy-cheap.com:5959"
            )
        if not self.ai_api_key:
            self.ai_api_key = os.environ.get(
                "GROQ_API_KEY", ""
            )
        if self.ai_model == "llama-3.1-8b-instant":
            groq_model = os.environ.get("GROQ_MODEL")
            if groq_model:
                self.ai_model = groq_model
        default_url = "https://api.groq.com/openai/v1"
        if self.ai_base_url == default_url:
            groq_key = os.environ.get("GROQ_API_KEY")
            if groq_key and not self.ai_api_key:
                self.ai_base_url = default_url

    @property
    def allowed_domains_list(self) -> list[str]:
        if not self.allowed_domains:
            return []
        return [
            d.strip().lower()
            for d in self.allowed_domains.split(",")
            if d.strip()
        ]


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

BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",
    "metadata.google.internal",
}

settings = Settings()

logger = logging.getLogger(__name__)


def is_url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
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
        host_lower = hostname.lower()
        for domain in allowed:
            if host_lower == domain.lower():
                return True
            if host_lower.endswith("." + domain.lower()):
                return True
        return False

    return True
