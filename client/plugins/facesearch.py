from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "facesearch"
    description = "OSINT face search: identify person from photo, find social media, public records, web presence"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._output_dir = Path(os.environ.get("FACSEARCH_DIR", "./facesearch"))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._api_key = os.environ.get("AI_API_KEY", "")
        self._base_url = os.environ.get("AI_BASE_URL", "https://api.groq.com/openai/v1")
        self._model = os.environ.get("AI_MODEL", "openai/gpt-oss-120b")

    async def execute(self, action: str = "analyze", **kw: Any) -> dict[str, Any]:
        actions = {
            "analyze": self._analyze_face,
            "search_web": self._search_web,
            "social_scan": self._social_scan,
            "full_osint": self._full_osint,
            "compare_faces": self._compare_faces,
            "extract_features": self._extract_features,
            "age_estimate": self._age_estimate,
            "ethnicity_guess": self._ethnicity_guess,
            "gender_estimate": self._gender_estimate,
            "build_profile": self._build_profile,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    async def _call_llm_vision(self, system: str, prompt: str, image_b64: str) -> str:
        if not self._api_key:
            return "Error: AI_API_KEY not configured"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self._model,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"{system}\n\n{prompt}"},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                            ],
                        }],
                        "max_tokens": 4096,
                        "temperature": 0.3,
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            return f"LLM API error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            return f"LLM connection error: {str(e)[:200]}"

    async def _call_llm_text(self, system: str, user: str) -> str:
        if not self._api_key:
            return "Error: AI_API_KEY not configured"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self._model,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "max_tokens": 4096,
                        "temperature": 0.3,
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            return f"LLM API error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            return f"LLM connection error: {str(e)[:200]}"

    def _load_b64(self, path: str = "", b64: str = "") -> str:
        if b64:
            return b64
        if path:
            data = Path(path).read_bytes()
            return base64.b64encode(data).decode()
        return ""

    async def _analyze_face(self, path: str = "", b64: str = "", **kw: Any) -> dict:
        image_b64 = self._load_b64(path, b64)
        if not image_b64:
            return {"error": "image path or b64 required"}

        system = (
            "Analyze this face photo in maximum detail. Extract and describe:\n"
            "1. Gender (estimated)\n"
            "2. Approximate age range\n"
            "3. Ethnicity/race estimation\n"
            "4. Hair: color, style, length\n"
            "5. Eyes: color, shape\n"
            "6. Skin tone\n"
            "7. Facial hair (if any)\n"
            "8. Distinguishing features (moles, scars, tattoos, piercings)\n"
            "9. Expression/mood\n"
            "10. Glasses/eyewear\n"
            "11. Overall appearance description\n"
            "12. Any notable characteristics\n"
            "Be specific and detailed. Use physical descriptors only."
        )
        result = await self._call_llm_vision(system, "Provide a comprehensive facial analysis of this person.", image_b64)
        return {"analysis": result, "source": path or "base64_input"}

    async def _extract_features(self, path: str = "", b64: str = "", **kw: Any) -> dict:
        image_b64 = self._load_b64(path, b64)
        if not image_b64:
            return {"error": "image required"}

        system = (
            "Extract a structured feature vector from this face. Output as JSON:\n"
            '{"gender":"", "age_range":"", "ethnicity":"", "hair_color":"", "hair_style":"", '
            '"eye_color":"", "skin_tone":"", "facial_hair":"", "glasses":"", '
            '"expression":"", "distinguishing_features":[], "confidence_scores":{}}'
        )
        result = await self._call_llm_vision(system, "Extract face features as structured JSON.", image_b64)
        return {"features": result}

    async def _age_estimate(self, path: str = "", b64: str = "", **kw: Any) -> dict:
        image_b64 = self._load_b64(path, b64)
        if not image_b64:
            return {"error": "image required"}
        system = "Estimate the person's age from this photo. Provide: exact estimated age, age range (low-high), confidence level, factors used for estimation."
        result = await self._call_llm_vision(system, "How old is this person?", image_b64)
        return {"age_estimate": result}

    async def _gender_estimate(self, path: str = "", b64: str = "", **kw: Any) -> dict:
        image_b64 = self._load_b64(path, b64)
        if not image_b64:
            return {"error": "image required"}
        system = "Estimate the gender of this person. Provide confidence level and features used for determination."
        result = await self._call_llm_vision(system, "What is the gender of this person?", image_b64)
        return {"gender_estimate": result}

    async def _ethnicity_guess(self, path: str = "", b64: str = "", **kw: Any) -> dict:
        image_b64 = self._load_b64(path, b64)
        if not image_b64:
            return {"error": "image required"}
        system = (
            "Estimate the ethnic/racial background of this person. "
            "Provide possible ethnicities with probability percentages and physical features used for estimation."
        )
        result = await self._call_llm_vision(system, "What is the ethnic background of this person?", image_b64)
        return {"ethnicity": result}

    async def _search_web(self, description: str = "", name_hint: str = "", **kw: Any) -> dict:
        if not description and not name_hint:
            return {"error": "description or name_hint required"}

        query = name_hint if name_hint else description[:200]
        results = {"platforms": [], "search_urls": [], "hints": []}

        platforms = {
            "google": f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "yandex": f"https://yandex.com/search/?text={query.replace(' ', '+')}",
            "bing": f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
            "facebook": f"https://www.facebook.com/search/people/?q={query.replace(' ', '+')}",
            "linkedin": f"https://www.linkedin.com/search/results/all/?keywords={query.replace(' ', '+')}",
            "twitter": f"https://twitter.com/search?q={query.replace(' ', '+')}",
            "instagram": f"https://www.instagram.com/explore/tags/{query.replace(' ', '')}/",
            "tiktok": f"https://www.tiktok.com/search?q={query.replace(' ', '+')}",
            "pinterest": f"https://www.pinterest.com/search/pins/?q={query.replace(' ', '+')}",
            "reddit": f"https://www.reddit.com/search/?q={query.replace(' ', '+')}",
            "youtube": f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
            "github": f"https://github.com/search?q={query.replace(' ', '+')}&type=users",
        }

        for name, url in platforms.items():
            results["search_urls"].append({"platform": name, "url": url})

        system = (
            "Given this face description, suggest search strategies:\n"
            "1. Likely name variations to search\n"
            "2. Professional keywords to search\n"
            "3. Location clues if any\n"
            "4. Hobby/interest keywords\n"
            "5. Any identifying text visible (clothing logos, etc)\n"
            "6. Best platforms to search on\n"
            "7. Reverse image search suggestions"
        )
        ai_result = await self._call_llm_text(system, f"Face description: {description}\nName hint: {name_hint}")
        results["ai_suggestions"] = ai_result

        return results

    async def _social_scan(self, description: str = "", name: str = "", location: str = "", **kw: Any) -> dict:
        platforms = []
        query = f"{name} {location}".strip() if name else description[:150]
        q = query.replace(" ", "+")

        social_checks = [
            ("Facebook", f"https://www.facebook.com/search/people/?q={q}"),
            ("Instagram", f"https://www.instagram.com/explore/tags/{q.replace('+','')}/"),
            ("Twitter/X", f"https://twitter.com/search?q={q}"),
            ("LinkedIn", f"https://www.linkedin.com/search/results/all/?keywords={q}"),
            ("TikTok", f"https://www.tiktok.com/search?q={q}"),
            ("YouTube", f"https://www.youtube.com/results?search_query={q}"),
            ("Reddit", f"https://www.reddit.com/search/?q={q}"),
            ("Pinterest", f"https://www.pinterest.com/search/pins/?q={q}"),
            ("GitHub", f"https://github.com/search?q={q}&type=users"),
            ("VKontakte", f"https://vk.com/search?c%5Bq%5D={q}"),
            ("Twitch", f"https://www.twitch.tv/search?term={q}"),
            ("DeviantArt", f"https://www.deviantart.com/search?q={q}"),
            ("SoundCloud", f"https://soundcloud.com/search/people?q={q}"),
            ("Medium", f"https://medium.com/search?q={q}"),
            ("Quora", f"https://www.quora.com/search?q={q}"),
        ]

        for platform, url in social_checks:
            platforms.append({"platform": platform, "search_url": url, "status": "check_manually"})

        return {
            "query": query,
            "platforms": platforms,
            "total_platforms": len(platforms),
            "note": "Open each URL to check results manually - automated scraping blocked by platforms",
        }

    async def _full_osint(self, path: str = "", b64: str = "", name: str = "", location: str = "", **kw: Any) -> dict:
        image_b64 = self._load_b64(path, b64)
        results = {"timestamp": time.time()}

        if image_b64:
            system = (
                "Perform comprehensive OSINT analysis of this person's face.\n"
                "Provide:\n"
                "1. Detailed physical description\n"
                "2. Estimated demographics (age, gender, ethnicity)\n"
                "3. Possible geographic origin\n"
                "4. Possible profession/occupation based on appearance\n"
                "5. Socio-economic indicators\n"
                "6. Cultural indicators\n"
                "7. Possible name suggestions based on features\n"
                "8. Similar-looking public figures\n"
                "9. Search strategy recommendations\n"
                "10. Reverse image search recommendations"
            )
            analysis = await self._call_llm_vision(system, "Full OSINT face analysis.", image_b64)
            results["face_analysis"] = analysis

        desc = name or results.get("face_analysis", "")
        if desc:
            search = await self._search_web(description=desc, name_hint=name)
            results["web_search"] = search

        if name or location:
            social = await self._social_scan(name=name, location=location, description=desc)
            results["social_media"] = social

        return results

    async def _compare_faces(self, path_a: str = "", path_b: str = "", b64_a: str = "", b64_b: str = "", **kw: Any) -> dict:
        img_a = self._load_b64(path_a, b64_a)
        img_b = self._load_b64(path_b, b64_b)
        if not img_a or not img_b:
            return {"error": "two images required"}

        system = (
            "Compare these two faces. Analyze:\n"
            "1. Are they the same person? (yes/no/uncertain)\n"
            "2. Similarity score (0-100%)\n"
            "3. Matching features\n"
            "4. Differing features\n"
            "5. Possible relationship (same person, siblings, unrelated)\n"
            "6. Confidence level"
        )

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self._model,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": system},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_a}"}},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b}"}},
                            ],
                        }],
                        "max_tokens": 4096,
                    },
                )
                r.raise_for_status()
                result = r.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            result = f"LLM API error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            result = f"LLM connection error: {str(e)[:200]}"

        return {"comparison": result, "image_a": path_a or "base64", "image_b": path_b or "base64"}

    async def _build_profile(self, path: str = "", b64: str = "", name: str = "", location: str = "", **kw: Any) -> dict:
        osint = await self._full_osint(path=path, b64=b64, name=name, location=location)

        profile = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "physical": osint.get("face_analysis", ""),
            "social_links": osint.get("social_media", {}).get("platforms", []),
            "search_urls": osint.get("web_search", {}).get("search_urls", []),
            "ai_suggestions": osint.get("web_search", {}).get("ai_suggestions", ""),
            "name_searched": name,
            "location_searched": location,
        }

        report_path = self._output_dir / f"profile_{int(time.time())}.json"
        report_path.write_text(json.dumps(profile, indent=2, default=str))
        profile["report_path"] = str(report_path)

        return profile
