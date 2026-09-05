from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.ai.agent_roles import AgentRole
from backend.ai.agent_protocol import (
    MsgType, AgentID, AgentMsg,
    pack_plan, pack_findings, pack_solution, pack_check, pack_verdict,
    unpack, extract_plan, extract_findings, extract_solution, extract_check,
)
from backend.ai.llm_provider import GroqAgentProvider, key_pool
from backend.ai.master_router import master_router, TaskComplexity
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
        self._stats = {
            "total": 0, "simple": 0, "medium": 0, "complex": 0,
            "agents_saved": 0, "avg_latency_ms": 0, "protocol_msgs": 0,
        }

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    async def process(self, request: VirtualAIRequest) -> VirtualAIResponse:
        async with self._lock:
            if self._active_workflows >= settings.max_ai_workflows:
                logger.warning(f"Workflow queue full ({self._active_workflows}), waiting...")
            while self._active_workflows >= settings.max_ai_workflows:
                self._lock.release()
                await asyncio.sleep(0.5)
                await self._lock.acquire()
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
                self._active_workflows = max(0, self._active_workflows - 1)

    async def _run_workflow(self, request: VirtualAIRequest) -> VirtualAIResponse:
        task_id = f"beta-{uuid.uuid4().hex[:12]}"
        user_message = self._extract_user_message(request)
        ctx = AIContext(
            task_id=task_id, original_request=user_message,
            max_deliberation_rounds=settings.max_deliberation_rounds,
        )

        logger.info(f"Starting AI workflow {task_id}: {user_message[:80]}...")

        decision = await master_router.route(user_message)
        logger.info(
            f"Router: complexity={decision.complexity.value}, "
            f"agents={[a.value for a in decision.agents]}"
        )

        self._stats["total"] += 1
        self._stats[decision.complexity.value] += 1
        self._stats["agents_saved"] += 5 - len(decision.agents)

        workflow_start = time.monotonic()

        for group in decision.parallel_groups:
            if len(group) == 1:
                role = group[0]
                if not self._should_skip(role, decision):
                    output = await self._run_agent(role, ctx)
                    self._store_output(ctx, role, output)
            else:
                tasks = []
                for role in group:
                    if not self._should_skip(role, decision):
                        tasks.append(self._run_agent(role, ctx))
                if tasks:
                    results = await asyncio.gather(*tasks)
                    for role, output in zip(
                        [r for r in group if not self._should_skip(r, decision)],
                        results,
                    ):
                        self._store_output(ctx, role, output)

        for round_num in range(ctx.max_deliberation_rounds):
            ctx.deliberation_round = round_num + 1
            if not decision.skip_critic and AgentRole.JUDGE in decision.agents:
                critic_task = self._run_agent(AgentRole.CRITIC, ctx)
                judge_task = self._run_agent(AgentRole.JUDGE, ctx)
                critic_output, judge_output = await asyncio.gather(critic_task, judge_task)

                ctx.agent_outputs["critic"] = critic_output
                ctx.agent_outputs["judge"] = judge_output

                if judge_output.success:
                    ctx.final_answer = judge_output.raw_response

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
                    logger.warning(f"Critic failed: {critic_output.error}")
                    break
            elif not decision.skip_critic:
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
                    logger.warning(f"Critic failed: {critic_output.error}")
                    break
            elif AgentRole.JUDGE in decision.agents:
                judge_output = await self._run_agent(AgentRole.JUDGE, ctx)
                ctx.agent_outputs["judge"] = judge_output
                if judge_output.success:
                    ctx.final_answer = judge_output.raw_response
                break

        if AgentRole.JUDGE not in ctx.agent_outputs:
            if AgentRole.JUDGE in decision.agents:
                judge_output = await self._run_agent(AgentRole.JUDGE, ctx)
                ctx.agent_outputs["judge"] = judge_output
                if judge_output.success:
                    ctx.final_answer = judge_output.raw_response
                else:
                    logger.warning(f"Judge failed: {judge_output.error}")
                    ctx.final_answer = self._build_fallback_answer(ctx)
            else:
                ctx.final_answer = self._build_fallback_answer(ctx)

        ctx.state = "completed"
        latency_ms = (time.monotonic() - workflow_start) * 1000
        self._stats["avg_latency_ms"] = (
            (self._stats["avg_latency_ms"] * (self._stats["total"] - 1) + latency_ms)
            / self._stats["total"]
        )

        logger.info(
            f"Workflow {task_id} done: {decision.complexity.value}, "
            f"agents={len(ctx.agent_outputs)}, latency={latency_ms:.0f}ms"
        )

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

    def _should_skip(self, role: AgentRole, decision) -> bool:
        if role == AgentRole.PLANNER and decision.skip_planner:
            return True
        if role == AgentRole.RESEARCHER and decision.skip_researcher:
            return True
        if role == AgentRole.CRITIC and decision.skip_critic:
            return True
        return False

    def _store_output(self, ctx: AIContext, role: AgentRole, output: AgentOutput) -> None:
        ctx.agent_outputs[role.value] = output
        if output.success:
            parsed = output.parsed
            if role == AgentRole.PLANNER:
                plan_data = extract_plan(AgentMsg(t=MsgType.PLAN, src=0, dst=0, payload=parsed)) if "s" in parsed else parsed
                ctx.plan = plan_data.get("plan", plan_data.get("s", []))
                ctx.needs_browser = plan_data.get("needs_browser", bool(plan_data.get("b", 0)))
                ctx.facts.extend(ctx.plan[:5])
            elif role == AgentRole.RESEARCHER:
                find_data = extract_findings(AgentMsg(t=MsgType.FIND, src=0, dst=0, payload=parsed)) if "f" in parsed else parsed
                ctx.evidence.extend(find_data.get("evidence", find_data.get("e", []))[:settings.max_evidence_items])
                ctx.facts.extend(find_data.get("findings", find_data.get("f", []))[:5])
            elif role == AgentRole.SOLVER:
                sol_data = extract_solution(AgentMsg(t=MsgType.SOLVE, src=0, dst=0, payload=parsed)) if "s" in parsed else parsed
                ctx.confidence = float(sol_data.get("confidence", sol_data.get("c", 0.7)))
                actions = sol_data.get("browser_actions", sol_data.get("ba", []))
                if ctx.needs_browser and actions:
                    ctx.browser_task_payload = {"task_id": ctx.task_id, "actions": actions}
            elif role == AgentRole.CRITIC:
                check_data = extract_check(AgentMsg(t=MsgType.CHECK, src=0, dst=0, payload=parsed)) if "ok" in parsed else parsed
        else:
            logger.warning(f"Agent {role.value} failed: {output.error}")

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
            logger.error(f"Agent {role.value} exception: {e}")
            return AgentOutput(
                agent=role, success=False, error=f"Exception: {e}",
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
        return "I apologize, but I was unable to process your request. Please try again."

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
                    "content": "Request timed out. Please try a simpler request.",
                },
                finish_reason="stop",
            )],
            usage=VirtualAIUsage(),
        )


orchestrator = AIOrchestrator()
