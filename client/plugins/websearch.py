from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "websearch"
    description = "Deep web search: Google, DuckDuckGo, Wikipedia, archive.org"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)

    async def execute(self, action: str = "search", **kw: Any) -> dict[str, Any]:
        actions = {
            "search": self._search,
            "wikipedia": self._wikipedia,
            "archive": self._archive,
            "fetch": self._fetch,
            "news": self._news,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    async def _search(self, query: str = "", num_results: int = 8, **kw: Any) -> dict:
        if not query:
            return {"error": "query required"}

        results = []
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"},
                )
                text = r.text

                import re
                for match in re.finditer(
                    r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:a|td|span|div)',
                    text, re.DOTALL
                ):
                    url, title, snippet = match.groups()
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                    if title:
                        results.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                            "source": "duckduckgo",
                        })
                    if len(results) >= num_results:
                        break

                if not results and text:
                    for match in re.finditer(r'class="result__a"[^>]*>(.*?)</a>', text, re.DOTALL):
                        title = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                        if title:
                            results.append({"title": title, "url": "", "snippet": "", "source": "duckduckgo"})
                        if len(results) >= num_results:
                            break

                return {"query": query, "results": results[:num_results], "count": len(results)}
        except Exception as e:
            return {"error": str(e), "query": query}

    async def _wikipedia(self, query: str = "", lang: str = "en", **kw: Any) -> dict:
        if not query:
            return {"error": "query required"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{query}",
                    headers={"User-Agent": "BetaBot/1.0"},
                )
                if r.status_code == 404:
                    sr = await client.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "list": "search", "srsearch": query,
                                "format": "json", "srlimit": 5},
                        headers={"User-Agent": "BetaBot/1.0"},
                    )
                    search_data = sr.json()
                    results = []
                    for item in search_data.get("query", {}).get("search", []):
                        results.append({
                            "title": item["title"],
                            "snippet": item.get("snippet", ""),
                            "url": f"https://{lang}.wikipedia.org/wiki/{item['title'].replace(' ', '_')}",
                        })
                    return {"query": query, "results": results, "source": "wikipedia_search"}

                data = r.json()
                return {
                    "title": data.get("title", ""),
                    "summary": data.get("extract", ""),
                    "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "thumbnail": data.get("thumbnail", {}).get("source", ""),
                    "source": "wikipedia",
                }
        except Exception as e:
            return {"error": str(e)}

    async def _archive(self, url: str = "", **kw: Any) -> dict:
        if not url:
            return {"error": "url required"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"https://archive.org/wayback/available?url={url}"
                )
                data = r.json()
                snapshots = data.get("archived_snapshots", {})
                closest = snapshots.get("closest", {})
                return {
                    "url": url,
                    "available": closest.get("status") == 200,
                    "snapshot_url": closest.get("url", ""),
                    "timestamp": closest.get("timestamp", ""),
                    "source": "archive.org",
                }
        except Exception as e:
            return {"error": str(e)}

    async def _fetch(self, url: str = "", max_chars: int = 5000, **kw: Any) -> dict:
        if not url:
            return {"error": "url required"}

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "BetaBot/1.0"})
                content_type = r.headers.get("content-type", "")

                if "text" in content_type or "html" in content_type:
                    text = r.text[:max_chars]
                    return {"url": url, "status": r.status_code, "content_type": content_type,
                            "content": text, "size": len(r.text)}
                return {"url": url, "status": r.status_code, "content_type": content_type,
                        "size": len(r.content), "binary": True}
        except Exception as e:
            return {"error": str(e)}

    async def _news(self, query: str = "", **kw: Any) -> dict:
        if not query:
            return {"error": "query required"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": query, "pageSize": 10, "sortBy": "publishedAt",
                            "apiKey": os.environ.get("NEWS_API_KEY", "")},
                )
                if r.status_code != 200:
                    return await self._search(query=query, **kw)
                data = r.json()
                articles = [
                    {"title": a["title"], "url": a["url"], "source": a["source"]["name"],
                     "published": a.get("publishedAt", ""), "description": a.get("description", "")}
                    for a in data.get("articles", [])
                ]
                return {"query": query, "articles": articles, "count": len(articles)}
        except Exception as e:
            return await self._search(query=query, **kw)
