from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "github"
    description = "GitHub operations: commit, push, issues, PR, repo info"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._token = os.environ.get("GITHUB_PAT", "")
        self._repo = os.environ.get("GITHUB_REPO", "dynamite-ai-coder/Beta")
        self._api = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github.v3+json"}
        if self._token:
            h["Authorization"] = f"token {self._token}"
        return h

    async def execute(self, action: str = "", **kwargs: Any) -> dict[str, Any]:
        actions = {
            "repo_info": self._repo_info,
            "list_commits": self._list_commits,
            "list_issues": self._list_issues,
            "create_issue": self._create_issue,
            "list_prs": self._list_prs,
            "create_pr": self._create_pr,
            "list_branches": self._list_branches,
            "file_content": self._file_content,
            "search_code": self._search_code,
            "repo_tree": self._repo_tree,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kwargs)

    async def _api_get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self._api}{path}", headers=self._headers(), params=params)
            r.raise_for_status()
            return r.json()

    async def _api_post(self, path: str, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{self._api}{path}", headers=self._headers(), json=data)
            r.raise_for_status()
            return r.json()

    async def _repo_info(self, **kw: Any) -> dict:
        data = await self._api_get(f"/repos/{self._repo}")
        return {
            "name": data["full_name"],
            "description": data.get("description", ""),
            "stars": data["stargazers_count"],
            "forks": data["forks_count"],
            "language": data.get("language", ""),
            "default_branch": data["default_branch"],
            "updated_at": data["updated_at"],
        }

    async def _list_commits(self, limit: int = 10, **kw: Any) -> dict:
        data = await self._api_get(f"/repos/{self._repo}/commits", params={"per_page": limit})
        commits = [
            {"sha": c["sha"][:8], "message": c["commit"]["message"].split("\n")[0],
             "author": c["commit"]["author"]["name"], "date": c["commit"]["author"]["date"]}
            for c in data
        ]
        return {"commits": commits, "count": len(commits)}

    async def _list_issues(self, state: str = "open", limit: int = 10, **kw: Any) -> dict:
        data = await self._api_get(f"/repos/{self._repo}/issues", params={"state": state, "per_page": limit})
        issues = [
            {"number": i["number"], "title": i["title"], "state": i["state"],
             "labels": [l["name"] for l in i["labels"]], "created_at": i["created_at"]}
            for i in data if "pull_request" not in i
        ]
        return {"issues": issues, "count": len(issues)}

    async def _create_issue(self, title: str = "", body: str = "", labels: list[str] | None = None, **kw: Any) -> dict:
        if not title:
            return {"error": "title required"}
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        data = await self._api_post(f"/repos/{self._repo}/issues", payload)
        return {"number": data["number"], "title": data["title"], "url": data["html_url"]}

    async def _list_prs(self, state: str = "open", **kw: Any) -> dict:
        data = await self._api_get(f"/repos/{self._repo}/pulls", params={"state": state})
        prs = [{"number": p["number"], "title": p["title"], "state": p["state"],
                "user": p["user"]["login"], "created_at": p["created_at"]} for p in data]
        return {"pull_requests": prs, "count": len(prs)}

    async def _create_pr(self, title: str = "", body: str = "", head: str = "main", base: str = "main", **kw: Any) -> dict:
        if not title:
            return {"error": "title required"}
        data = await self._api_post(f"/repos/{self._repo}/pulls", {
            "title": title, "body": body, "head": head, "base": base,
        })
        return {"number": data["number"], "title": data["title"], "url": data["html_url"]}

    async def _list_branches(self, **kw: Any) -> dict:
        data = await self._api_get(f"/repos/{self._repo}/branches")
        return {"branches": [b["name"] for b in data]}

    async def _file_content(self, path: str = "", ref: str = "main", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        data = await self._api_get(f"/repos/{self._repo}/contents/{path}", params={"ref": ref})
        import base64
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return {"path": data["path"], "size": data["size"], "content": content[:10000]}

    async def _search_code(self, query: str = "", **kw: Any) -> dict:
        if not query:
            return {"error": "query required"}
        data = await self._api_get("/search/code", params={"q": f"{query} repo:{self._repo}"})
        results = [
            {"path": item["path"], "name": item["name"], "url": item["html_url"]}
            for item in data.get("items", [])[:10]
        ]
        return {"results": results, "count": data.get("total_count", 0)}

    async def _repo_tree(self, path: str = "", ref: str = "main", **kw: Any) -> dict:
        data = await self._api_get(f"/repos/{self._repo}/contents/{path}", params={"ref": ref})
        items = [{"name": i["name"], "type": i["type"], "path": i["path"]} for i in data]
        return {"items": items, "path": path or "/"}
