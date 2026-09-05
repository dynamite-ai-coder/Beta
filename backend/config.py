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

    # AI (legacy single-agent - still used as fallback)
    ai_api_key: str = ""
    ai_model: str = "openai/gpt-oss-120b"
    ai_base_url: str = "https://api.groq.com/openai/v1"
    ai_provider: str = "groq"

    # Virtual AI API
    beta_api_key: str = ""
    virtual_model_name: str = "beta-virtual-ai"
    max_ai_workflows: int = 1
    max_deliberation_rounds: int = 2
    max_context_size: int = 8000
    max_agent_output_size: int = 4096
    max_evidence_items: int = 10

    # Multi-agent Groq configuration
    groq_agent_1_api_key: str = ""
    groq_agent_1_model: str = "openai/gpt-oss-120b"
    groq_agent_1_base_url: str = "https://api.groq.com/openai/v1"

    groq_agent_2_api_key: str = ""
    groq_agent_2_model: str = "qwen/qwen3.6-27b"
    groq_agent_2_base_url: str = "https://api.groq.com/openai/v1"

    groq_agent_3_api_key: str = ""
    groq_agent_3_model: str = "allam-2-7b"
    groq_agent_3_base_url: str = "https://api.groq.com/openai/v1"

    groq_agent_4_api_key: str = ""
    groq_agent_4_model: str = "qwen/qwen3.8-27b"
    groq_agent_4_base_url: str = "https://api.groq.com/openai/v1"

    groq_agent_5_api_key: str = ""
    groq_agent_5_model: str = "openai/gpt-oss-20b"
    groq_agent_5_base_url: str = "https://api.groq.com/openai/v1"

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

    # Browser (Windows client only)
    browser_executable: str | None = None
    headless: bool = True
    browser_engine: str = "selenium"  # selenium | browser-use

    # Proxy (Proxy-Cheap)
    proxy_enabled: bool = False
    proxy_secret: str = ""
    proxy_apikey: str = ""
    proxy_url: str = ""

    # Tor (optional anonymity layer)
    use_tor: bool = False
    tor_bridges: str = ""
    tor_socks_port: int = 9050

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
        self.beta_api_key = self.beta_api_key.strip()
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
            self.ai_api_key = os.environ.get("GROQ_API_KEY", "")
        if not self.beta_api_key:
            self.beta_api_key = os.environ.get("BETA_API_KEY", self.api_auth_token)

        # Allow env var to override default model
        env_groq_model = os.environ.get("AI_MODEL", "")
        if env_groq_model:
            self.ai_model = env_groq_model

        agent_keys = [
            "groq_agent_1_api_key", "groq_agent_2_api_key",
            "groq_agent_3_api_key", "groq_agent_4_api_key",
            "groq_agent_5_api_key",
        ]
        for i, key in enumerate(agent_keys, 1):
            env_key = f"GROQ_AGENT_{i}_API_KEY"
            val = getattr(self, key)
            if not val:
                setattr(self, key, os.environ.get(env_key, self.ai_api_key))
            env_model = f"GROQ_AGENT_{i}_MODEL"
            model_key = f"groq_agent_{i}_model"
            env_m = os.environ.get(env_model)
            if env_m:
                setattr(self, model_key, env_m)
            env_url = f"GROQ_AGENT_{i}_BASE_URL"
            url_key = f"groq_agent_{i}_base_url"
            env_u = os.environ.get(env_url)
            if env_u:
                setattr(self, url_key, env_u)

    def get_agent_config(self, agent_number: int) -> dict[str, str]:
        return {
            "api_key": getattr(self, f"groq_agent_{agent_number}_api_key", self.ai_api_key),
            "model": getattr(self, f"groq_agent_{agent_number}_model", self.ai_model),
            "base_url": getattr(self, f"groq_agent_{agent_number}_base_url", self.ai_base_url),
        }

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
