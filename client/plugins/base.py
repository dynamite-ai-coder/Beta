from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class PluginBase(ABC):
    name: str = "base"
    description: str = ""
    version: str = "1.0.0"
    author: str = ""

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._enabled = True
        self._logger = logging.getLogger(f"plugin.{self.name}")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the plugin action. Returns result dict."""
        ...

    async def on_load(self) -> None:
        """Called when plugin is loaded."""
        pass

    async def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "enabled": self._enabled,
        }
