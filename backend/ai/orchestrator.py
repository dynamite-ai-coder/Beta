from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.ai.agent_roles import AgentRole
from backend.ai.llm_provider import GroqAgentProvider
from backend.ai.models import (
    AIContext, AgentOutput, VirtualAIRequest, VirtualAIResponse,
    VirtualAIChoice, VirtualAIUsage, BrowserTaskRequest,
)
from backend.config import settings

logger = logging.getLogger(__name__)

WORKFLOW_TIMEOUT = 180


class AIOrchestrator:
    def __init__(self) -> None:
        self.agents: dict[AgentRole, GroqAgentProvider] = {}
        for i, role in enumerate(AgentRole, 1):
            self.agents[role] = GroqAgentProvider(role, i)
        self._active_workflows = 0
        self._lock = asyncio.Lock()

    async def process(self, request: VirtualAIRequest) -> VirtualAIResponse:
        async with self._lock:
            if self._active_workflows >= settings.max_ai_workflows:
                raise RuntimeError("Max concurrent AI workflows reached")
            self._active_workflows += 1

        try:
            return await asyncio.wait_for(
                self._run_workflow(request),
                timeout=WORKFLOW_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("AI workflow timed out")
            return self._build_timeout_response(request)
        finally:
            async with self._lock:
                self._active_workflows -= 1

    async def _run_workflow(self, request: VirtualAIRequest) -> VirtualAIResponse:
        task_id = f"beta-{uuid.uuid4().hex[:12]}"
        user_message = self._extract_user_message(request)
        ctx = AIContext(
            task_id=task_id, original_request=user_message,
            max_deliberation_rounds=settings.max_deliberation_rounds,
        )

        logger.info(f"Starting AI workflow {task_id}: {user_message[:80]}...")

        plan_output = await self._run_agent(AgentRole.PLANNER, ctx)
        ctx.agent_outputs["planner"] = plan_output
        if plan_output.success:
            parsed = plan_output.parsed
            ctx.plan = parsed.get("plan", [])
            ctx.needs_browser = parsed.get("needs_browser", False)
            ctx.facts.extend(parsed.get("plan", [])[:5])
        else:
            logger.warning(f"Planner agent failed: {plan_output.error}")

        researcher_output = await self._run_agent(AgentRole.RESEARCHER, ctx)
        ctx.agent_outputs["researcher"] = researcher_output
        if researcher_output.success:
            parsed = researcher_output.parsed
            ctx.evidence.extend(parsed.get("evidence", [])[:settings.max_evidence_items])
            ctx.facts.extend(parsed.get("findings", [])[:5])
        else:
            logger.warning(f"Researcher agent failed: {researcher_output.error}")

        solver_output = await self._run_agent(AgentRole.SOLVER, ctx)
        ctx.agent_outputs["solver"] = solver_output
        if solver_output.success:
            parsed = solver_output.parsed
            ctx.confidence = float(parsed.get("confidence", 0.7))
            ctx.browser_task_payload = None
            if ctx.needs_browser and parsed.get("browser_actions"):
                ctx.browser_task_payload = {
                    "task_id": task_id,
                    "actions": parsed["browser_actions"],
                }
        else:
            logger.warning(f"Solver agent failed: {solver_output.error}")

        for round_num in range(ctx.max_deliberation_rounds):
            ctx.deliberation_round = round_num + 1
            critic_output = await self._run_agent(AgentRole.CRITIC, ctx)
            ctx.agent_outputs["critic"] = critic_output

            if critic_output.success:
                parsed = critic_output.parsed
                if parsed.get("approved", True):
                    break
                issues = parsed.get("issues", [])
                for issue in issues:
                    ctx.errors.append(
                        f"[{issue.get('severity', 'low')}] {issue.get('description', '')}"
                    )
                if round_num < ctx.max_deliberation_rounds - 1:
                    solver_output = await self._run_agent(AgentRole.SOLVER, ctx)
                    ctx.agent_outputs["solver"] = solver_output
            else:
                logger.warning(f"Critic agent failed: {critic_output.error}")
                break

        judge_output = await self._run_agent(AgentRole.JUDGE, ctx)
        ctx.agent_outputs["judge"] = judge_output
        if judge_output.success:
            ctx.final_answer = judge_output.raw_response
        else:
            logger.warning(f"Judge agent failed: {judge_output.error}")
            ctx.final_answer = self._build_fallback_answer(ctx)

        ctx.state = "completed"
        logger.info(f"Workflow {task_id} completed, confidence={ctx.confidence:.2f}")

        prompt_tokens = sum(o.tokens_used for o in ctx.agent_outputs.values())
        completion_tokens = len(ctx.final_answer.split()) * 2

        return VirtualAIResponse(
            id=task_id,
            created=int(datetime.now(timezone.utc).timestamp()),
            model=settings.virtual_model_name,
            choices=[VirtualAIChoice(
                index=0,
                message={"role": "assistant", "content": ctx.final_answer},
                finish_reason="stop",
            )],
            usage=VirtualAIUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    async def _run_agent(self, role: AgentRole, ctx: AIContext) -> AgentOutput:
        agent = self.agents[role]
        context_summary = ctx.get_compact_summary()

        if role == AgentRole.PLANNER:
            prompt = ctx.original_request
        elif role == AgentRole.JUDGE:
            summaries = []
            for name, out in ctx.agent_outputs.items():
                if out.success:
                    summaries.append(f"[{name}] {out.raw_response[:500]}")
            prompt = (
                f"Original request: {ctx.original_request}\n\n"
                f"Agent outputs:\n" + "\n".join(summaries)
            )
            if ctx.errors:
                prompt += f"\n\nCritic issues: {json.dumps(ctx.errors[:5])}"
        else:
            prompt = f"Original request: {ctx.original_request}\nPlan: {', '.join(ctx.plan[:5])}"
            if ctx.evidence:
                prompt += f"\nEvidence: {', '.join(ctx.evidence[:5])}"
            if ctx.errors:
                prompt += f"\nKnown issues: {', '.join(ctx.errors[:3])}"

        try:
            return await agent.chat(prompt, context_summary)
        except Exception as e:
            logger.error(f"Agent {role.value} raised exception: {e}")
            return AgentOutput(
                agent=role, success=False, error=f"Agent exception: {e}",
            )

    def _extract_user_message(self, request: VirtualAIRequest) -> str:
        for msg in reversed(request.messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _build_fallback_answer(self, ctx: AIContext) -> str:
        if ctx.agent_outputs.get("solver") and ctx.agent_outputs["solver"].success:
            return ctx.agent_outputs["solver"].raw_response
        if ctx.agent_outputs.get("researcher") and ctx.agent_outputs["researcher"].success:
            return ctx.agent_outputs["researcher"].raw_response
        return (
            "I apologize, but I was unable to process your request "
            "at this time. Please try again."
        )

    def _build_timeout_response(self, request: VirtualAIRequest) -> VirtualAIResponse:
        task_id = f"beta-{uuid.uuid4().hex[:12]}"
        return VirtualAIResponse(
            id=task_id,
            created=int(datetime.now(timezone.utc).timestamp()),
            model=settings.virtual_model_name,
            choices=[VirtualAIChoice(
                index=0,
                message={
                    "role": "assistant",
                    "content": (
                        "I apologize, but the request timed out. "
                        "Please try a simpler request or try again later."
                    ),
                },
                finish_reason="stop",
            )],
            usage=VirtualAIUsage(),
        )


orchestrator = AIOrchestrator()
