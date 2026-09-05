from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

from backend.ai.agent_roles import AgentRole, get_agent_prompt
from backend.ai.llm_provider import key_pool
from backend.config import settings

logger = logging.getLogger(__name__)


class TaskComplexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class RoutingDecision:
    def __init__(
        self,
        agents: list[AgentRole],
        complexity: TaskComplexity,
        reasoning: str,
        skip_planner: bool = False,
        skip_researcher: bool = False,
        skip_critic: bool = False,
        parallel_groups: list[list[AgentRole]] = None,
    ):
        self.agents = agents
        self.complexity = complexity
        self.reasoning = reasoning
        self.skip_planner = skip_planner
        self.skip_researcher = skip_researcher
        self.skip_critic = skip_critic
        self.parallel_groups = parallel_groups or [agents]


ROUTER_SYSTEM_PROMPT = """You are a Master Router Agent. Analyze the user's request and decide which AI agents should process it.

Available agents:
1. PLANNER - Creates execution plans for complex multi-step tasks
2. RESEARCHER - Analyzes information, finds evidence and data
3. SOLVER - Solves problems, generates solutions, writes code
4. CRITIC - Verifies quality, finds errors, challenges assumptions
5. JUDGE - Synthesizes final answer from all agents

Respond with a JSON object:
{
  "complexity": "simple|medium|complex",
  "agents_needed": ["agent1", "agent2", ...],
  "reasoning": "brief explanation",
  "skip_planner": true/false,
  "skip_researcher": true/false,
  "skip_critic": true/false
}

Rules:
- SIMPLE (facts, definitions, translations): Only SOLVER + JUDGE
- MEDIUM (analysis, explanations): SOLVER + CRITIC + JUDGE
- COMPLEX (multi-step, research, code): All agents
- Always include JUDGE as final agent
- Be concise in reasoning"""


class MasterRouter:
    def __init__(self) -> None:
        self._cache: dict[str, RoutingDecision] = {}
        self._cache_ttl = 300

    def _simple_route(self, message: str) -> Optional[RoutingDecision]:
        msg_lower = message.lower().strip()

        simple_patterns = [
            "co to jest", "what is", "what are", "define", "definition",
            "ile to", "how much", "how many", "count",
            "tłumacz", "translate", "przetłumacz",
            "podaj", "give me", "show me",
            "tak", "nie", "yes", "no", "ok",
            "dzięki", "thank", "thanks",
        ]
        if any(p in msg_lower for p in simple_patterns) and len(message) < 100:
            return RoutingDecision(
                agents=[AgentRole.SOLVER, AgentRole.JUDGE],
                complexity=TaskComplexity.SIMPLE,
                reasoning="Simple query - direct answer",
                skip_planner=True,
                skip_researcher=True,
                skip_critic=True,
                parallel_groups=[[AgentRole.SOLVER]],
            )

        medium_patterns = [
            "wyjaśnij", "explain", "opisz", "describe",
            "porównaj", "compare", "różnice", "differences",
            "analizuj", "analyze", "przeanalizuj",
            "co myślisz", "what do you think",
            "jak", "how does", "how to",
        ]
        if any(p in msg_lower for p in medium_patterns) and len(message) < 500:
            return RoutingDecision(
                agents=[AgentRole.SOLVER, AgentRole.CRITIC, AgentRole.JUDGE],
                complexity=TaskComplexity.MEDIUM,
                reasoning="Medium complexity - analysis needed",
                skip_planner=True,
                skip_researcher=True,
                parallel_groups=[[AgentRole.SOLVER]],
            )

        return None

    async def route(self, message: str) -> RoutingDecision:
        cached = self._cache.get(message[:200])
        if cached:
            return cached

        simple = self._simple_route(message)
        if simple:
            self._cache[message[:200]] = simple
            return simple

        try:
            decision = await self._llm_route(message)
            self._cache[message[:200]] = decision
            return decision
        except Exception as e:
            logger.warning(f"Router LLM failed: {e}, using default full pipeline")
            return self._default_route(message)

    async def _llm_route(self, message: str) -> RoutingDecision:
        key = await key_pool.acquire()
        if not key:
            return self._default_route(message)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.groq_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.virtual_model_name,
                        "messages": [
                            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                            {"role": "user", "content": f"Analyze this request:\n\n{message[:500]}"},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 300,
                    },
                )
                key_pool.mark_used(key)

                if resp.status_code != 200:
                    return self._default_route(message)

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_routing(content, message)

        except Exception as e:
            logger.debug(f"Router request failed: {e}")
            return self._default_route(message)

    def _parse_routing(self, content: str, message: str) -> RoutingDecision:
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return self._default_route(message)

        complexity = TaskComplexity(data.get("complexity", "medium"))
        agents_needed = data.get("agents_needed", ["planner", "researcher", "solver", "critic", "judge"])

        role_map = {
            "planner": AgentRole.PLANNER,
            "researcher": AgentRole.RESEARCHER,
            "solver": AgentRole.SOLVER,
            "critic": AgentRole.CRITIC,
            "judge": AgentRole.JUDGE,
        }
        agents = []
        for name in agents_needed:
            if name.lower() in role_map:
                agents.append(role_map[name.lower()])

        if AgentRole.JUDGE not in agents:
            agents.append(AgentRole.JUDGE)

        parallel_groups = []
        if AgentRole.PLANNER in agents and AgentRole.RESEARCHER in agents:
            parallel_groups.append([AgentRole.PLANNER, AgentRole.RESEARCHER])
            remaining = [a for a in agents if a not in (AgentRole.PLANNER, AgentRole.RESEARCHER)]
        else:
            remaining = agents[:]

        if remaining:
            parallel_groups.append(remaining)

        return RoutingDecision(
            agents=agents,
            complexity=complexity,
            reasoning=data.get("reasoning", "LLM routing"),
            skip_planner=data.get("skip_planner", False),
            skip_researcher=data.get("skip_researcher", False),
            skip_critic=data.get("skip_critic", False),
            parallel_groups=parallel_groups,
        )

    def _default_route(self, message: str) -> RoutingDecision:
        return RoutingDecision(
            agents=list(AgentRole),
            complexity=TaskComplexity.COMPLEX,
            reasoning="Default full pipeline",
            parallel_groups=[
                [AgentRole.PLANNER, AgentRole.RESEARCHER],
                [AgentRole.SOLVER],
                [AgentRole.CRITIC],
                [AgentRole.JUDGE],
            ],
        )


master_router = MasterRouter()
