"""
Beta AI Shared Protocol
Compact communication between LocalAI (Phi-3-mini) and MultiAgent (5 Groq agents).

Usage:
  LocalAI server: receives compact requests, returns compact responses
  Backend: sends compact requests to LocalAI, parses responses

Format: base85 encoded header (5 bytes) + compact JSON body
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class MsgType(IntEnum):
    # LocalAI messages
    PREPROCESS = 0x10
    PREPROCESS_REPLY = 0x11
    CLASSIFY = 0x12
    CLASSIFY_REPLY = 0x13
    EXTRACT = 0x14
    EXTRACT_REPLY = 0x15
    SIMPLIFY = 0x16
    SIMPLIFY_REPLY = 0x17

    # MultiAgent messages
    ROUTE = 0x20
    ROUTE_REPLY = 0x21
    AGENT_INPUT = 0x22
    AGENT_OUTPUT = 0x23
    AGENT_ERROR = 0x24

    # System messages
    PING = 0xF0
    PONG = 0xF1
    STATUS = 0xF2


class Complexity(IntEnum):
    SIMPLE = 0
    MEDIUM = 1
    COMPLEX = 2


@dataclass
class ProtocolMsg:
    type: int
    src: str = ""
    dst: str = ""
    id: int = 0
    payload: dict = field(default_factory=dict)
    ref: int = 0

    def encode(self) -> str:
        header = struct.pack(">BBHBB", self.type & 0xFF, 0, self.id & 0xFFFF, 0, self.ref & 0xFF)
        body = json.dumps(self.payload, separators=(",", ":"), ensure_ascii=False)
        raw = header + body.encode("utf-8")
        return base64.b85encode(raw).decode("ascii")

    @classmethod
    def decode(cls, raw: str) -> "ProtocolMsg":
        try:
            data = base64.b85decode(raw.encode("ascii"))
            t, _, id_, _, ref = struct.unpack(">BBHBB", data[:5])
            body = json.loads(data[5:].decode("utf-8"))
            return cls(type=t, id=id_, ref=ref, payload=body)
        except Exception:
            return cls(type=0, payload={"raw": raw})


# === LocalAI Request/Response ===

def pack_preprocess(message: str, file_context: str = "", lang: str = "pl") -> str:
    return ProtocolMsg(
        type=MsgType.PREPROCESS, src="backend", dst="localai",
        payload={"m": message, "fc": file_context, "l": lang},
    ).encode()


def pack_classify(message: str) -> str:
    return ProtocolMsg(
        type=MsgType.CLASSIFY, src="backend", dst="localai",
        payload={"m": message},
    ).encode()


def pack_extract(text: str, keys: list[str] = None) -> str:
    return ProtocolMsg(
        type=MsgType.EXTRACT, src="backend", dst="localai",
        payload={"t": text, "k": keys or ["solution", "answer", "result"]},
    ).encode()


def pack_simplify(text: str, max_words: int = 100) -> str:
    return ProtocolMsg(
        type=MsgType.SIMPLIFY, src="backend", dst="localai",
        payload={"t": text, "w": max_words},
    ).encode()


def unpack_preprocess_reply(raw: str) -> dict:
    msg = ProtocolMsg.decode(raw)
    p = msg.payload
    return {
        "processed": p.get("p", ""),
        "original": p.get("o", ""),
        "success": bool(p.get("ok", 0)),
        "latency_ms": p.get("ms", 0),
    }


def unpack_classify_reply(raw: str) -> dict:
    msg = ProtocolMsg.decode(raw)
    p = msg.payload
    return {
        "complexity": p.get("cx", "medium"),
        "agents": p.get("ag", []),
        "skip": p.get("sk", []),
        "confidence": p.get("c", 0.7),
    }


def unpack_extract_reply(raw: str) -> dict:
    msg = ProtocolMsg.decode(raw)
    p = msg.payload
    return {
        "extracted": p.get("e", {}),
        "plain_text": p.get("pt", ""),
        "success": bool(p.get("ok", 0)),
    }


def unpack_simplify_reply(raw: str) -> dict:
    msg = ProtocolMsg.decode(raw)
    p = msg.payload
    return {
        "simplified": p.get("s", ""),
        "original_words": p.get("ow", 0),
        "simplified_words": p.get("sw", 0),
    }


# === MultiAgent Messages ===

def pack_agent_input(agent: str, task: str, context: str, extra: dict = None) -> str:
    payload = {"a": agent, "t": task, "ctx": context}
    if extra:
        payload.update(extra)
    return ProtocolMsg(
        type=MsgType.AGENT_INPUT, src="orchestrator", dst="agent",
        payload=payload,
    ).encode()


def pack_agent_output(agent: str, result: str, confidence: float = 0.7, tokens: int = 0) -> str:
    return ProtocolMsg(
        type=MsgType.AGENT_OUTPUT, src="agent", dst="orchestrator",
        payload={"a": agent, "r": result, "c": round(confidence, 2), "tk": tokens},
    ).encode()


def pack_agent_error(agent: str, error: str, code: str = "ERR") -> str:
    return ProtocolMsg(
        type=MsgType.AGENT_ERROR, src="agent", dst="orchestrator",
        payload={"a": agent, "e": error, "code": code},
    ).encode()


# === System Messages ===

def pack_ping() -> str:
    return ProtocolMsg(type=MsgType.PING, src="system", dst="system").encode()


def pack_pong() -> str:
    return ProtocolMsg(type=MsgType.PONG, src="system", dst="system").encode()


def pack_status(info: dict) -> str:
    return ProtocolMsg(
        type=MsgType.STATUS, src="system", dst="system",
        payload=info,
    ).encode()


# === Utility ===

def decode_any(raw: str) -> ProtocolMsg:
    return ProtocolMsg.decode(raw)


def msg_type_name(msg: ProtocolMsg) -> str:
    names = {
        0x10: "PREPROCESS", 0x11: "PREPROCESS_REPLY",
        0x12: "CLASSIFY", 0x13: "CLASSIFY_REPLY",
        0x14: "EXTRACT", 0x15: "EXTRACT_REPLY",
        0x16: "SIMPLIFY", 0x17: "SIMPLIFY_REPLY",
        0x20: "ROUTE", 0x21: "ROUTE_REPLY",
        0x22: "AGENT_INPUT", 0x23: "AGENT_OUTPUT", 0x24: "AGENT_ERROR",
        0xF0: "PING", 0xF1: "PONG", 0xF2: "STATUS",
    }
    return names.get(msg.type, f"UNKNOWN(0x{msg.type:02X})")


def token_savings(compact: str, json_equivalent: str) -> dict:
    compact_tokens = len(compact) // 4
    json_tokens = len(json_equivalent) // 4
    return {
        "compact_tokens": compact_tokens,
        "json_tokens": json_tokens,
        "saved": json_tokens - compact_tokens,
        "savings_pct": round((1 - compact_tokens / max(json_tokens, 1)) * 100, 1),
    }
