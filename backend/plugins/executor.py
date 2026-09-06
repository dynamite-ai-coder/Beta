from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CLIENT_URL = "http://127.0.0.1:23400"

PLUGIN_CATALOG = {
    "websearch": {
        "description": "Web search: Google, DuckDuckGo, Wikipedia, news, fetch pages",
        "actions": {
            "search": {"query": "string", "num_results": "int"},
            "wikipedia": {"query": "string", "lang": "string"},
            "news": {"query": "string"},
            "fetch": {"url": "string", "max_chars": "int"},
        },
    },
    "screenshot": {
        "description": "Browser screenshots: capture, compare, save",
        "actions": {
            "capture": {"url": "string"},
            "capture_url": {"url": "string", "width": "int", "height": "int"},
            "compare": {"url1": "string", "url2": "string"},
        },
    },
    "coder": {
        "description": "Code execution, analysis, file operations, shell commands",
        "actions": {
            "run": {"code": "string", "language": "string"},
            "shell": {"command": "string"},
            "read": {"path": "string"},
            "write": {"path": "string", "content": "string"},
            "analyze": {"code": "string"},
            "lint": {"path": "string"},
            "format": {"path": "string"},
        },
    },
    "deepthink": {
        "description": "Chain-of-thought reasoning, analysis, brainstorming",
        "actions": {
            "think": {"question": "string", "context": "string"},
            "analyze": {"topic": "string", "depth": "string"},
            "brainstorm": {"topic": "string", "count": "int"},
            "compare": {"options": "list", "criteria": "string"},
            "plan": {"goal": "string", "constraints": "string"},
        },
    },
    "media": {
        "description": "Image editing: resize, crop, filters, watermark, convert",
        "actions": {
            "resize": {"path": "string", "width": "int", "height": "int"},
            "crop": {"path": "string", "x": "int", "y": "int", "w": "int", "h": "int"},
            "blur": {"path": "string", "radius": "int"},
            "sharpen": {"path": "string"},
            "grayscale": {"path": "string"},
            "sepia": {"path": "string"},
            "watermark": {"path": "string", "text": "string"},
            "convert": {"path": "string", "format": "string"},
            "info": {"path": "string"},
        },
    },
    "videoeditor": {
        "description": "Video editing: trim, merge, effects, audio, convert",
        "actions": {
            "info": {"path": "string"},
            "trim": {"path": "string", "start": "float", "end": "float"},
            "merge": {"inputs": "list"},
            "speed": {"path": "string", "factor": "float"},
            "convert": {"path": "string", "format": "string"},
            "compress": {"path": "string", "quality": "int"},
            "to_gif": {"path": "string", "fps": "int"},
        },
    },
    "videorec": {
        "description": "Record browser activity as video",
        "actions": {
            "start": {"url": "string", "fps": "int"},
            "stop": {},
            "status": {},
            "make_video": {},
        },
    },
    "github": {
        "description": "GitHub: repos, commits, issues, PRs, code search",
        "actions": {
            "repo_info": {"owner": "string", "repo": "string"},
            "list_commits": {"owner": "string", "repo": "string", "limit": "int"},
            "list_issues": {"owner": "string", "repo": "string", "state": "string"},
            "create_issue": {"owner": "string", "repo": "string", "title": "string", "body": "string"},
            "list_prs": {"owner": "string", "repo": "string"},
            "search_code": {"query": "string"},
        },
    },
    "facesearch": {
        "description": "OSINT face search: identify people, social media, public records",
        "actions": {
            "analyze": {"image_url": "string"},
            "search_web": {"image_url": "string"},
            "full_osint": {"image_url": "string"},
            "build_profile": {"image_url": "string"},
        },
    },
    "silverbullet": {
        "description": "SilverBullet automation scripts: create, run, templates",
        "actions": {
            "create": {"name": "string", "description": "string"},
            "run": {"name": "string"},
            "from_description": {"description": "string"},
            "templates_list": {},
        },
    },
    "aiagent": {
        "description": "Multi-provider AI: Groq, OpenAI, Anthropic, Ollama, DeepSeek",
        "actions": {
            "chat": {"message": "string", "provider": "string", "model": "string"},
            "test": {"provider": "string"},
            "providers": {},
            "recommend": {},
        },
    },
}


def get_tools_description() -> str:
    lines = ["AVAILABLE TOOLS (execute via plugin system):"]
    for name, info in PLUGIN_CATALOG.items():
        lines.append(f"\n[{name}] {info['description']}")
        for action, params in info["actions"].items():
            param_str = ", ".join(f"{k}:{v}" for k, v in params.items())
            lines.append(f"  - {name}/{action}({param_str})")
    return "\n".join(lines)


async def execute_plugin(plugin_name: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if plugin_name not in PLUGIN_CATALOG:
        return {"error": f"Unknown plugin: {plugin_name}", "available": list(PLUGIN_CATALOG.keys())}

    plugin_info = PLUGIN_CATALOG[plugin_name]
    if action not in plugin_info["actions"]:
        return {"error": f"Unknown action: {action}", "available": list(plugin_info["actions"].keys())}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{CLIENT_URL}/api/plugins/execute",
                json={"name": plugin_name, "action": action, "params": params or {}},
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Plugin returned {resp.status_code}", "detail": resp.text[:500]}
    except httpx.ConnectError:
        return {"error": "Client not available"}
    except Exception as e:
        return {"error": str(e)}
