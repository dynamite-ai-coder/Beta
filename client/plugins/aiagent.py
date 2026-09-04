from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)

PROVIDERS = {
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768",
                    "gemma2-9b-it", "meta-llama/llama-4-scout-17b-16e-instruct"],
        "free_tier": True,
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1-preview", "o1-mini"],
        "free_tier": False,
    },
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-4-20250514", "claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
        "free_tier": False,
    },
    "ollama": {
        "name": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "env_key": "",
        "models": ["llama3.2", "llama3.1", "mistral", "codellama", "phi3", "gemma2"],
        "free_tier": True,
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
        "free_tier": False,
    },
    "together": {
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "env_key": "TOGETHER_API_KEY",
        "models": ["meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
                    "mistralai/Mixtral-8x7B-Instruct-v0.1"],
        "free_tier": False,
    },
}


class Plugin(PluginBase):
    name = "aiagent"
    description = "Multi-provider AI agent: Groq, OpenAI, Anthropic, Ollama, DeepSeek, Together"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._config_path = Path(os.environ.get("AI_AGENT_CONFIG", "./ai_agent_config.json"))
        self._providers_config = self._load_config()
        self._env = self._detect_environment()

    def _detect_environment(self) -> dict:
        is_termux = False
        is_android = False
        is_windows = sys.platform == "win32"
        is_linux = sys.platform == "linux"
        ram_mb = 0

        try:
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            ram_mb = int(line.split()[1]) // 1024
                            break
        except Exception:
            pass

        try:
            if os.path.exists("/system/build.prop"):
                is_android = True
            if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
                is_termux = True
        except Exception:
            pass

        if not ram_mb and is_windows:
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                c_ulonglong = ctypes.c_ulonglong
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                                ("ullTotalPhys", c_ulonglong), ("ullAvailPhys", c_ulonglong)]
                mem = MEMORYSTATUSEX()
                mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
                ram_mb = mem.ullTotalPhys // (1024 * 1024)
            except Exception:
                ram_mb = 8192

        recommended_model = "llama-3.1-8b-instant"
        recommended_provider = "groq"
        if is_termux or (is_android and ram_mb < 6000):
            recommended_model = "tinyllama"
            recommended_provider = "ollama"
        elif ram_mb < 4000:
            recommended_model = "tinyllama"
            recommended_provider = "ollama"
        elif ram_mb < 8000:
            recommended_model = "llama-3.1-8b-instant"
            recommended_provider = "groq"

        return {
            "platform": "termux" if is_termux else ("android" if is_android else ("windows" if is_windows else "linux")),
            "is_termux": is_termux,
            "is_android": is_android,
            "is_windows": is_windows,
            "is_linux": is_linux,
            "ram_mb": ram_mb,
            "python": platform.python_version(),
            "recommended_provider": recommended_provider,
            "recommended_model": recommended_model,
        }

    def _load_config(self) -> dict:
        if self._config_path.exists():
            try:
                return json.loads(self._config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_config(self) -> None:
        self._config_path.write_text(json.dumps(self._providers_config, indent=2), encoding="utf-8")

    def _get_key(self, provider: str) -> str:
        cfg = self._providers_config.get(provider, {})
        key = cfg.get("api_key", "")
        if not key:
            env_key = PROVIDERS.get(provider, {}).get("env_key", "")
            if env_key:
                key = os.environ.get(env_key, "")
        return key

    def _get_base_url(self, provider: str) -> str:
        cfg = self._providers_config.get(provider, {})
        return cfg.get("base_url", PROVIDERS.get(provider, {}).get("base_url", ""))

    def _get_model(self, provider: str) -> str:
        cfg = self._providers_config.get(provider, {})
        return cfg.get("model", PROVIDERS.get(provider, {}).get("models", [""])[0])

    async def execute(self, action: str = "providers", **kw: Any) -> dict[str, Any]:
        actions = {
            "providers": self._list_providers,
            "configure": self._configure,
            "chat": self._chat,
            "chat_stream": self._chat_stream,
            "models": self._list_models,
            "set_key": self._set_key,
            "set_model": self._set_model,
            "detect_env": self._detect,
            "recommend": self._recommend,
            "status": self._status,
            "test": self._test,
            "multi_chat": self._multi_chat,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    async def _list_providers(self, **kw: Any) -> dict:
        result = []
        for pid, info in PROVIDERS.items():
            cfg = self._providers_config.get(pid, {})
            has_key = bool(self._get_key(pid))
            result.append({
                "id": pid, "name": info["name"], "free_tier": info["free_tier"],
                "configured": has_key, "base_url": self._get_base_url(pid),
                "current_model": cfg.get("model", ""),
            })
        return {"providers": result, "environment": self._env}

    async def _configure(self, provider: str = "", api_key: str = "", model: str = "",
                         base_url: str = "", **kw: Any) -> dict:
        if not provider:
            return {"error": "provider required"}
        if provider not in PROVIDERS:
            return {"error": f"Unknown provider: {provider}", "available": list(PROVIDERS.keys())}

        if provider not in self._providers_config:
            self._providers_config[provider] = {}

        if api_key:
            self._providers_config[provider]["api_key"] = api_key
        if model:
            self._providers_config[provider]["model"] = model
        if base_url:
            self._providers_config[provider]["base_url"] = base_url

        self._save_config()
        return {"status": "configured", "provider": provider,
                "model": self._get_model(provider), "has_key": bool(self._get_key(provider))}

    async def _set_key(self, provider: str = "", api_key: str = "", **kw: Any) -> dict:
        if not provider or not api_key:
            return {"error": "provider and api_key required"}
        if provider not in self._providers_config:
            self._providers_config[provider] = {}
        self._providers_config[provider]["api_key"] = api_key
        self._save_config()
        return {"status": "ok", "provider": provider}

    async def _set_model(self, provider: str = "", model: str = "", **kw: Any) -> dict:
        if not provider or not model:
            return {"error": "provider and model required"}
        if provider not in self._providers_config:
            self._providers_config[provider] = {}
        self._providers_config[provider]["model"] = model
        self._save_config()
        return {"status": "ok", "provider": provider, "model": model}

    async def _detect(self, **kw: Any) -> dict:
        return self._env

    async def _recommend(self, **kw: Any) -> dict:
        env = self._env
        rec = {"environment": env["platform"], "ram_mb": env["ram_mb"]}

        if env["is_termux"] or env["ram_mb"] < 4000:
            rec["recommendation"] = {
                "provider": "ollama",
                "model": "tinyllama",
                "reason": f"Termux/Android detected with {env['ram_mb']}MB RAM. Use TinyLlama (~637MB) locally.",
                "install": "pkg install ollama && ollama pull tinyllama",
                "alt_provider": "groq",
                "alt_model": "llama-3.1-8b-instant",
                "alt_reason": "Free Groq API as fallback (no local RAM needed)",
            }
        elif env["ram_mb"] < 8000:
            rec["recommendation"] = {
                "provider": "groq",
                "model": "llama-3.1-8b-instant",
                "reason": f"{env['ram_mb']}MB RAM. Use free Groq API for fast inference.",
                "alt_provider": "ollama",
                "alt_model": "phi3",
                "alt_reason": "Local Phi-3 (~2GB) as fallback",
            }
        else:
            rec["recommendation"] = {
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "reason": f"{env['ram_mb']}MB RAM available. Use Groq 70B for best quality.",
                "alt_provider": "ollama",
                "alt_model": "llama3.2",
                "alt_reason": "Local Llama 3.2 3B for privacy-sensitive tasks",
            }

        return rec

    async def _status(self, **kw: Any) -> dict:
        providers_status = []
        for pid, info in PROVIDERS.items():
            key = self._get_key(pid)
            model = self._get_model(pid)
            providers_status.append({
                "provider": pid, "name": info["name"],
                "configured": bool(key), "model": model,
                "env_key": info["env_key"],
                "env_key_set": bool(os.environ.get(info["env_key"], "")),
            })

        return {
            "environment": self._env,
            "providers": providers_status,
            "config_path": str(self._config_path),
        }

    async def _chat(self, message: str = "", provider: str = "", model: str = "",
                    system: str = "", temperature: float = 0.7, max_tokens: int = 4096,
                    **kw: Any) -> dict:
        if not message:
            return {"error": "message required"}

        provider = provider or self._env.get("recommended_provider", "groq")
        if provider not in PROVIDERS:
            return {"error": f"Unknown provider: {provider}"}

        key = self._get_key(provider)
        base_url = self._get_base_url(provider)
        use_model = model or self._get_model(provider)

        if not key and provider != "ollama":
            return {"error": f"No API key for {provider}. Use configure/set_key action."}

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["Authorization"] = f"Bearer {key}"

                payload: dict[str, Any] = {
                    "model": use_model, "messages": messages,
                    "temperature": temperature, "max_tokens": max_tokens,
                }

                if provider == "anthropic":
                    headers["x-api-key"] = key
                    headers["anthropic-version"] = "2023-06-01"
                    if system:
                        payload["system"] = system
                    payload["messages"] = [{"role": "user", "content": message}]

                r = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)

                if r.status_code != 200:
                    error_text = r.text[:500]
                    return {"error": f"API error {r.status_code}: {error_text}", "provider": provider}

                data = r.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})

                return {
                    "response": content, "provider": provider, "model": use_model,
                    "usage": usage, "temperature": temperature,
                }
        except httpx.TimeoutException:
            return {"error": "Request timed out (60s)", "provider": provider}
        except Exception as e:
            return {"error": str(e), "provider": provider}

    async def _chat_stream(self, message: str = "", provider: str = "", model: str = "",
                           system: str = "", **kw: Any) -> dict:
        return await self._chat(message=message, provider=provider, model=model, system=system, **kw)

    async def _list_models(self, provider: str = "", **kw: Any) -> dict:
        if provider and provider in PROVIDERS:
            return {"provider": provider, "models": PROVIDERS[provider]["models"]}
        all_models = {}
        for pid, info in PROVIDERS.items():
            all_models[pid] = info["models"]
        return {"providers": all_models}

    async def _multi_chat(self, message: str = "", providers: list[str] | None = None,
                          system: str = "", **kw: Any) -> dict:
        if not message:
            return {"error": "message required"}

        if not providers:
            providers = ["groq"]

        tasks = []
        for p in providers:
            tasks.append(self._chat(message=message, provider=p, system=system))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                responses.append({"provider": providers[i], "error": str(result)})
            else:
                responses.append(result)

        return {"responses": responses, "count": len(responses)}

    async def _test(self, provider: str = "", **kw: Any) -> dict:
        result = await self._chat(
            message="Say 'test ok' and nothing else.",
            provider=provider, max_tokens=10,
        )
        if "error" in result:
            return {"provider": provider or "auto", "status": "failed", "error": result["error"]}
        return {"provider": result.get("provider", ""), "status": "ok", "response": result.get("response", "")}
