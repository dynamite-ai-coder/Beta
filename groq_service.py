#!/usr/bin/env python3
"""Persistent Groq Accelerator - runs as background service."""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path("/public/Beta/.env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GROQ] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/groq_accelerator.log"),
    ],
)
logger = logging.getLogger("groq")

def _load_keys() -> list[str]:
    csv = os.environ.get("GROQ_KEYS", "")
    if csv:
        return [k.strip() for k in csv.split(",") if k.strip()]
    keys = []
    for var in ["AI_API_KEY", "GROQ_AGENT_1_API_KEY", "GROQ_AGENT_2_API_KEY",
                "GROQ_AGENT_3_API_KEY", "GROQ_AGENT_4_API_KEY", "GROQ_AGENT_5_API_KEY"]:
        k = os.environ.get(var, "")
        if k:
            keys.append(k)
    return keys

KEYS = _load_keys()
MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "allam-2-7b",
    "qwen/qwen3.8-27b",
]
TASK_MODELS = {
    "chat": ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"],
    "reasoning": ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"],
    "code": ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"],
    "creative": ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"],
    "summarize": ["allam-2-7b", "qwen/qwen3.6-27b"],
    "classify": ["allam-2-7b", "qwen/qwen3.6-27b"],
}
STATS = [{"calls": 0, "errors": 0, "reset": time.time()} for _ in range(len(KEYS))]
MODEL_IDX = 0
RESULTS_DIR = Path("/tmp/groq_results")
RESULTS_DIR.mkdir(exist_ok=True)


def _check_rate(idx: int) -> bool:
    now = time.time()
    if now - STATS[idx]["reset"] >= 60:
        STATS[idx] = {"calls": 0, "errors": 0, "reset": now}
        return True
    return STATS[idx]["calls"] < 28


def _pick_key() -> int:
    return min(range(len(KEYS)), key=lambda i: STATS[i]["calls"])


async def ask(message: str, task: str = "chat", model: str = None, temp: float = 0.3) -> Optional[str]:
    global MODEL_IDX
    candidates = TASK_MODELS.get(task, TASK_MODELS["chat"])
    use_model = model or candidates[MODEL_IDX % len(candidates)]
    MODEL_IDX += 1

    for attempt in range(len(KEYS)):
        idx = (_pick_key() + attempt) % len(KEYS)
        if not _check_rate(idx):
            continue
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {KEYS[idx]}", "Content-Type": "application/json"},
                    json={"model": use_model, "messages": [{"role": "user", "content": message}], "temperature": temp, "max_tokens": 2048},
                )
                if r.status_code == 200:
                    STATS[idx]["calls"] += 1
                    result = r.json()["choices"][0]["message"]["content"]
                    return result
                else:
                    STATS[idx]["errors"] += 1
                    logger.warning(f"Key{idx+1} error {r.status_code}: {r.text[:100]}")
        except Exception as e:
            STATS[idx]["errors"] += 1
            logger.error(f"Key{idx+1} exception: {e}")
    return None


async def ask_multi(messages: list, task: str = "chat", model: str = None, temp: float = 0.3) -> Optional[str]:
    global MODEL_IDX
    candidates = TASK_MODELS.get(task, TASK_MODELS["chat"])
    use_model = model or candidates[MODEL_IDX % len(candidates)]
    MODEL_IDX += 1

    for attempt in range(len(KEYS)):
        idx = (_pick_key() + attempt) % len(KEYS)
        if not _check_rate(idx):
            continue
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {KEYS[idx]}", "Content-Type": "application/json"},
                    json={"model": use_model, "messages": messages, "temperature": temp, "max_tokens": 2048},
                )
                if r.status_code == 200:
                    STATS[idx]["calls"] += 1
                    return r.json()["choices"][0]["message"]["content"]
                else:
                    STATS[idx]["errors"] += 1
        except Exception as e:
            STATS[idx]["errors"] += 1
    return None


def print_stats():
    total = sum(s["calls"] for s in STATS)
    errors = sum(s["errors"] for s in STATS)
    logger.info(f"Stats: {total} calls, {errors} errors")
    for i, s in enumerate(STATS):
        logger.info(f"  Key{i+1}: {s['calls']} calls, {s['errors']} errors")


async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        data = await asyncio.wait_for(reader.readline(), timeout=120)
        if not data:
            return
        req = json.loads(data.decode().strip())
        
        msg = req.get("message", "")
        task = req.get("task", "chat")
        temp = req.get("temp", 0.3)
        messages = req.get("messages")
        
        if messages:
            result = await ask_multi(messages, task=task, temp=temp)
        else:
            result = await ask(msg, task=task, temp=temp)
        
        resp = json.dumps({"result": result, "stats": [s.copy() for s in STATS]})
        writer.write((resp + "\n").encode())
        await writer.drain()
    except Exception as e:
        logger.error(f"Request error: {e}")
        writer.write(json.dumps({"result": None, "error": str(e)}).encode() + b"\n")
        await writer.drain()
    finally:
        writer.close()


async def main():
    server = await asyncio.start_server(handle_request, "127.0.0.1", 9876)
    logger.info(f"Groq Accelerator listening on 127.0.0.1:9876")
    logger.info(f"Keys: {len(KEYS)}, Models: {len(MODELS)}")
    
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
