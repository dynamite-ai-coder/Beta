from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "deepthink"
    description = "Chain-of-thought reasoning, multi-step analysis, problem decomposition"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._api_key = os.environ.get("AI_API_KEY", "")
        self._base_url = os.environ.get("AI_BASE_URL", "https://api.groq.com/openai/v1")
        self._model = os.environ.get("AI_MODEL", "llama-3.3-70b-versatile")

    async def execute(self, action: str = "think", **kw: Any) -> dict[str, Any]:
        actions = {
            "think": self._think,
            "decompose": self._decompose,
            "analyze": self._analyze,
            "compare": self._compare,
            "brainstorm": self._brainstorm,
            "critique": self._critique,
            "summarize": self._summarize,
            "plan": self._plan,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    async def _call_llm(self, system: str, user: str, temperature: float = 0.7) -> str:
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
                        "temperature": temperature,
                        "max_tokens": 4096,
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            return f"LLM API error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            return f"LLM connection error: {str(e)[:200]}"

    async def _think(self, question: str = "", steps: int = 5, **kw: Any) -> dict:
        if not question:
            return {"error": "question required"}

        system = (
            "You are a deep reasoning engine. Think step by step.\n"
            "For each step, provide:\n"
            "1. What you're considering\n"
            "2. Your reasoning\n"
            "3. What you conclude from this step\n"
            "Then provide a final synthesis.\n"
            "Be thorough, logical, and consider edge cases."
        )

        result = await self._call_llm(system, question)
        return {"question": question, "reasoning": result, "steps": steps, "model": self._model}

    async def _decompose(self, problem: str = "", **kw: Any) -> dict:
        if not problem:
            return {"error": "problem required"}

        system = (
            "Decompose this problem into smaller, manageable sub-problems.\n"
            "For each sub-problem:\n"
            "- State it clearly\n"
            "- Identify dependencies on other sub-problems\n"
            "- Estimate difficulty (easy/medium/hard)\n"
            "- Suggest an approach\n"
            "Output as structured list."
        )

        result = await self._call_llm(system, problem)
        return {"problem": problem, "decomposition": result, "model": self._model}

    async def _analyze(self, text: str = "", focus: str = "general", **kw: Any) -> dict:
        if not text:
            return {"error": "text required"}

        system = (
            f"Perform deep {focus} analysis of the following text.\n"
            "Consider:\n"
            "- Key points and arguments\n"
            "- Assumptions and biases\n"
            "- Strengths and weaknesses\n"
            "- Implications and consequences\n"
            "- Missing information\n"
            "Provide structured analysis with evidence."
        )

        result = await self._call_llm(system, text)
        return {"analysis": result, "focus": focus, "model": self._model}

    async def _compare(self, option_a: str = "", option_b: str = "", criteria: str = "", **kw: Any) -> dict:
        if not option_a or not option_b:
            return {"error": "option_a and option_b required"}

        prompt = f"Compare these two options:\n\nOption A: {option_a}\n\nOption B: {option_b}"
        if criteria:
            prompt += f"\n\nFocus criteria: {criteria}"

        system = (
            "Provide a thorough comparison:\n"
            "1. Pros and cons of each\n"
            "2. Use case suitability\n"
            "3. Risk assessment\n"
            "4. Cost/benefit analysis\n"
            "5. Recommendation with justification"
        )

        result = await self._call_llm(system, prompt)
        return {"option_a": option_a, "option_b": option_b, "comparison": result, "model": self._model}

    async def _brainstorm(self, topic: str = "", count: int = 10, **kw: Any) -> dict:
        if not topic:
            return {"error": "topic required"}

        system = (
            f"Brainstorm {count} creative ideas about this topic.\n"
            "For each idea:\n"
            "- Title\n"
            "- Brief description (2-3 sentences)\n"
            "- Feasibility (low/medium/high)\n"
            "- Impact (low/medium/high)\n"
            "Think outside the box. Include unconventional ideas."
        )

        result = await self._call_llm(system, topic, temperature=0.9)
        return {"topic": topic, "ideas": result, "count": count, "model": self._model}

    async def _critique(self, text: str = "", perspective: str = "adversarial", **kw: Any) -> dict:
        if not text:
            return {"error": "text required"}

        system = (
            f"Provide a {perspective} critique of this:\n"
            "1. Identify logical fallacies\n"
            "2. Challenge assumptions\n"
            "3. Find counterarguments\n"
            "4. Point out weaknesses\n"
            "5. Suggest improvements\n"
            "Be constructive but thorough."
        )

        result = await self._call_llm(system, text, temperature=0.3)
        return {"critique": result, "perspective": perspective, "model": self._model}

    async def _summarize(self, text: str = "", style: str = "concise", **kw: Any) -> dict:
        if not text:
            return {"error": "text required"}

        styles = {
            "concise": "Summarize in 2-3 sentences, keeping only key points.",
            "detailed": "Provide a detailed summary with all important points.",
            "bullet": "Summarize as bullet points, one per key idea.",
            "executive": "Write an executive summary: key findings, implications, recommendations.",
        }

        system = styles.get(style, styles["concise"])
        result = await self._call_llm(system, text)
        return {"summary": result, "style": style, "model": self._model}

    async def _plan(self, goal: str = "", context: str = "", **kw: Any) -> dict:
        if not goal:
            return {"error": "goal required"}

        prompt = f"Goal: {goal}"
        if context:
            prompt += f"\nContext: {context}"

        system = (
            "Create a detailed execution plan:\n"
            "1. Define clear milestones\n"
            "2. Break into actionable tasks\n"
            "3. Estimate time for each task\n"
            "4. Identify dependencies\n"
            "5. List required resources\n"
            "6. Identify risks and mitigation\n"
            "7. Define success criteria"
        )

        result = await self._call_llm(system, prompt)
        return {"goal": goal, "plan": result, "model": self._model}
