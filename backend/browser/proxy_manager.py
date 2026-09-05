from __future__ import annotations

import logging
import os
import random
import threading
from typing import Optional

logger = logging.getLogger(__name__)

PROXY_FILE = os.environ.get("PROXY_FILE", "proxy.txt")


class ProxyEntry:
    __slots__ = ("ip", "port", "user", "passwd", "protocol")

    def __init__(self, ip: str, port: str, user: str, password: str, protocol: str = "http") -> None:
        self.ip = ip
        self.port = port
        self.user = user
        self.passwd = password
        self.protocol = protocol

    @property
    def url(self) -> str:
        if self.user and self.passwd:
            return f"{self.protocol}://{self.user}:{self.passwd}@{self.ip}:{self.port}"
        return f"{self.protocol}://{self.ip}:{self.port}"

    @property
    def auth_url(self) -> str:
        return f"{self.ip}:{self.port}:{self.user}:{self.passwd}"

    def __repr__(self) -> str:
        return f"ProxyEntry({self.ip}:{self.port})"


class ProxyManager:
    def __init__(self, proxy_file: str = PROXY_FILE) -> None:
        self._proxy_file = proxy_file
        self._proxies: list[ProxyEntry] = []
        self._index = 0
        self._lock = threading.Lock()
        self._load_proxies()

    def _load_proxies(self) -> None:
        if not os.path.exists(self._proxy_file):
            logger.info("No proxy file found at %s", self._proxy_file)
            return

        seen = set()
        with open(self._proxy_file, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) < 4:
                    logger.warning("Invalid proxy on line %d: %s", line_num, line)
                    continue
                ip = parts[0]
                port = parts[1]
                user = parts[2]
                password = parts[3]
                protocol = "http"

                key = f"{ip}:{port}:{user}"
                if key in seen:
                    continue
                seen.add(key)

                self._proxies.append(ProxyEntry(ip, port, user, password, protocol))

        logger.info("Loaded %d unique proxies from %s", len(self._proxies), self._proxy_file)

    @property
    def count(self) -> int:
        return len(self._proxies)

    @property
    def enabled(self) -> bool:
        return len(self._proxies) > 0

    def get_next(self) -> Optional[ProxyEntry]:
        with self._lock:
            if not self._proxies:
                return None
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index = (self._index + 1) % len(self._proxies)
            return proxy

    def get_random(self) -> Optional[ProxyEntry]:
        if not self._proxies:
            return None
        return random.choice(self._proxies)

    def get_by_index(self, index: int) -> Optional[ProxyEntry]:
        if 0 <= index < len(self._proxies):
            return self._proxies[index]
        return None

    def get_all(self) -> list[dict]:
        return [
            {"ip": p.ip, "port": p.port, "protocol": p.protocol, "index": i}
            for i, p in enumerate(self._proxies)
        ]

    def reload(self) -> int:
        with self._lock:
            self._proxies.clear()
            self._index = 0
            self._load_proxies()
            return len(self._proxies)

    def remove_by_index(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self._proxies):
                self._proxies.pop(index)
                if self._index >= len(self._proxies):
                    self._index = 0
                return True
            return False


proxy_manager = ProxyManager()
