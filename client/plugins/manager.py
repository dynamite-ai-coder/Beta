from __future__ import annotations

import importlib
import logging
from typing import Any

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)

BUILTIN_PLUGINS = [
    "client.plugins.github",
    "client.plugins.screenshot",
    "client.plugins.video",
    "client.plugins.websearch",
    "client.plugins.coder",
    "client.plugins.deepthink",
    "client.plugins.media",
    "client.plugins.videoeditor",
    "client.plugins.facesearch",
    "client.plugins.silverbullet",
    "client.plugins.aiagent",
]


class PluginManager:
    def __init__(self) -> None:
        self._plugins: dict[str, PluginBase] = {}

    @property
    def plugins(self) -> dict[str, PluginBase]:
        return dict(self._plugins)

    def get(self, name: str) -> PluginBase | None:
        return self._plugins.get(name)

    async def load_builtin(self, config: Any = None) -> None:
        for module_name in BUILTIN_PLUGINS:
            try:
                mod = importlib.import_module(module_name)
                plugin_cls = getattr(mod, "Plugin")
                plugin = plugin_cls(config=config)
                self._plugins[plugin.name] = plugin
                await plugin.on_load()
                logger.info("Loaded plugin: %s v%s", plugin.name, plugin.version)
            except Exception as e:
                logger.warning("Failed to load plugin %s: %s", module_name, e)

    async def unload(self, name: str) -> bool:
        plugin = self._plugins.pop(name, None)
        if plugin:
            await plugin.on_unload()
            return True
        return False

    async def execute(self, plugin_name: str, **kwargs: Any) -> dict[str, Any]:
        plugin = self._plugins.get(plugin_name)
        if not plugin:
            return {"error": f"Plugin '{plugin_name}' not found"}
        if not plugin.enabled:
            return {"error": f"Plugin '{plugin_name}' is disabled"}
        try:
            return await plugin.execute(**kwargs)
        except Exception as e:
            logger.error("Plugin %s error: %s", plugin_name, e)
            return {"error": str(e)}

    def list_all(self) -> list[dict[str, Any]]:
        return [p.info() for p in self._plugins.values()]


plugin_manager = PluginManager()
