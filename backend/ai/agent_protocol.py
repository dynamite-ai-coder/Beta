from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class MsgType(IntEnum):
    PLAN = 0x01
    FIND = 0x02
    SOLVE = 0x03
    CHECK = 0x04
    VERDICT = 0x05
    ROUTE = 0x06
    ERROR = 0x07
    FACT = 0x08
    EVIDENCE = 0x09
    ACTION = 0x0A


class Severity(IntEnum):
    LOW = 0
    MED = 1
    HIGH = 2
    CRIT = 3


class AgentID(IntEnum):
    ROUTER = 0
    PLAN = 1
    RESEARCH = 2
    SOLVE = 3
    CRITIC = 4
    JUDGE = 5


@dataclass
class AgentMsg:
    t: int
    src: int
    dst: int
    fid: int = 0
    payload: dict = field(default_factory=dict)
    ref: int = 0

    def encode(self) -> str:
        header = struct.pack(">BBBBB", self.t, self.src, self.dst, self.fid, self.ref)
        body = json.dumps(self.payload, separators=(",", ":"), ensure_ascii=False)
        return base64.b85encode(header + body.encode()).decode()

    @classmethod
    def decode(cls, raw: str) -> "AgentMsg":
        try:
            data = base64.b85decode(raw.encode())
            t, src, dst, fid, ref = struct.unpack(">BBBBB", data[:5])
            body = json.loads(data[5:].decode())
            return cls(t=t, src=src, dst=dst, fid=fid, ref=ref, payload=body)
        except Exception:
            return cls(t=0, src=0, dst=0, payload={"raw": raw})


PLAN_SCHEMA = "plan:steps[],browser:bool,strategy:str,tasks:[{id,desc,dep[]}]"
FIND_SCHEMA = "findings[],evidence[],missing[],conf:float,analysis:str"
SOLVE_SCHEMA = "solution:str,browser_actions:[{action,target}],reasoning:str,conf:float,alts[]"
CHECK_SCHEMA = "ok:bool,issues:[{sev,desc,agent}],challenges[],suggestions[],quality:float"
VERDICT_SCHEMA = "answer:str,conf:float,sources[]"
ROUTE_SCHEMA = "complexity:str,agents:[str],reasoning:str,skip:[str]"


def pack_plan(steps: list[str], browser: bool, strategy: str, tasks: list[dict]) -> str:
    return AgentMsg(
        t=MsgType.PLAN, src=AgentID.PLAN, dst=AgentID.SOLVE,
        payload={"s": steps, "b": 1 if browser else 0, "x": strategy, "t": tasks}
    ).encode()


def pack_findings(findings: list[str], evidence: list[str], missing: list[str], conf: float, analysis: str) -> str:
    return AgentMsg(
        t=MsgType.FIND, src=AgentID.RESEARCH, dst=AgentID.SOLVE,
        payload={"f": findings, "e": evidence, "m": missing, "c": round(conf, 2), "a": analysis}
    ).encode()


def pack_solution(solution: str, actions: list[dict], reasoning: str, conf: float, alts: list[str]) -> str:
    return AgentMsg(
        t=MsgType.SOLVE, src=AgentID.SOLVE, dst=AgentID.CRITIC,
        payload={"s": solution, "ba": actions, "r": reasoning, "c": round(conf, 2), "alt": alts}
    ).encode()


def pack_check(ok: bool, issues: list[dict], challenges: list[str], suggestions: list[str], quality: float) -> str:
    return AgentMsg(
        t=MsgType.CHECK, src=AgentID.CRITIC, dst=AgentID.SOLVE,
        payload={"ok": 1 if ok else 0, "i": issues, "ch": challenges, "sg": suggestions, "q": round(quality, 2)}
    ).encode()


def pack_verdict(answer: str, conf: float, sources: list[str]) -> str:
    return AgentMsg(
        t=MsgType.VERDICT, src=AgentID.JUDGE, dst=AgentID.ROUTER,
        payload={"ans": answer, "c": round(conf, 2), "src": sources}
    ).encode()


def pack_route(complexity: str, agents: list[str], reasoning: str, skip: list[str]) -> str:
    return AgentMsg(
        t=MsgType.ROUTE, src=AgentID.ROUTER, dst=AgentID.ROUTER,
        payload={"cx": complexity, "ag": agents, "rx": reasoning, "sk": skip}
    ).encode()


def pack_error(code: str, msg: str, agent: int) -> str:
    return AgentMsg(
        t=MsgType.ERROR, src=agent, dst=AgentID.ROUTER,
        payload={"code": code, "msg": msg}
    ).encode()


def unpack(msg_str: str) -> AgentMsg:
    return AgentMsg.decode(msg_str)


def extract_plan(msg: AgentMsg) -> dict:
    p = msg.payload
    return {
        "plan": p.get("s", []),
        "needs_browser": bool(p.get("b", 0)),
        "strategy": p.get("x", ""),
        "subtasks": p.get("t", []),
    }


def extract_findings(msg: AgentMsg) -> dict:
    p = msg.payload
    return {
        "findings": p.get("f", []),
        "evidence": p.get("e", []),
        "missing_info": p.get("m", []),
        "confidence": p.get("c", 0.7),
        "analysis": p.get("a", ""),
    }


def extract_solution(msg: AgentMsg) -> dict:
    p = msg.payload
    return {
        "solution": p.get("s", ""),
        "browser_actions": p.get("ba", []),
        "reasoning": p.get("r", ""),
        "confidence": p.get("c", 0.7),
        "alternatives": p.get("alt", []),
    }


def extract_check(msg: AgentMsg) -> dict:
    p = msg.payload
    return {
        "approved": bool(p.get("ok", 1)),
        "issues": p.get("i", []),
        "challenges": p.get("ch", []),
        "suggestions": p.get("sg", []),
        "overall_quality": p.get("q", 0.7),
    }


def to_tokens(text: str) -> int:
    return len(text) // 4


def savings_vs_json(compact: str, original_json: str) -> dict:
    return {
        "compact_tokens": to_tokens(compact),
        "json_tokens": to_tokens(original_json),
        "saved_tokens": to_tokens(original_json) - to_tokens(compact),
        "savings_pct": round((1 - to_tokens(compact) / max(to_tokens(original_json), 1)) * 100, 1),
    }
