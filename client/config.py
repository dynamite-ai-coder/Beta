from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ClientConfig:
    api_url: str = "http://localhost:8000"
    api_token: str = ""

    @classmethod
    def from_env(cls) -> ClientConfig:
        return cls(
            api_url=os.environ.get("API_URL", "http://localhost:8000"),
            api_token=os.environ.get("API_AUTH_TOKEN", ""),
        )
