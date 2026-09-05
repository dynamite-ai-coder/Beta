#!/usr/bin/env python3
"""
Beta AI Groq Multi-Key Accelerator
Używa 4 działających kluczy Groq do równoległej komunikacji z różnymi modelami.
Darmowy tier: ~30 RPM na klucz, 4 klucze = ~120 RPM łącznie.

Użycie:
  export GROQ_KEYS="key1,key2,key3,key4"
  python3 groq_accelerator.py

Lub z pliku .env (jeśli istnieje):
  GROQ_API_KEY=key1
  GROQ_AGENT_1_API_KEY=key2
  GROQ_AGENT_2_API_KEY=key3
  GROQ_AGENT_3_API_KEY=key4
"""

import asyncio
import os
import time
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

def _load_keys() -> list[str]:
    """Załaduj klucze z env: GROQ_KEYS (csv) lub pojedynczych zmiennych."""
    csv = os.environ.get("GROQ_KEYS", "")
    if csv:
        return [k.strip() for k in csv.split(",") if k.strip()]
    keys = []
    for var in ["GROQ_API_KEY", "GROQ_AGENT_1_API_KEY", "GROQ_AGENT_2_API_KEY",
                "GROQ_AGENT_3_API_KEY", "GROQ_AGENT_4_API_KEY"]:
        k = os.environ.get(var, "")
        if k:
            keys.append(k)
    return keys

GROQ_KEYS = _load_keys()

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

STATS = [{"calls": 0, "errors": 0, "reset": time.time()} for _ in range(4)]
LOCK = asyncio.Lock()
MODEL_IDX = 0


def _check_rate(idx: int) -> bool:
    now = time.time()
    if now - STATS[idx]["reset"] >= 60:
        STATS[idx] = {"calls": 0, "errors": 0, "reset": now}
        return True
    return STATS[idx]["calls"] < 28


def get_stats():
    return STATS[:]


async def _call(idx: int, model: str, messages: list, temperature=0.3, max_tokens=2048):
    if not _check_rate(idx):
        await asyncio.sleep(2)
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEYS[idx]}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            )
            if r.status_code == 200:
                STATS[idx]["calls"] += 1
                return r.json()["choices"][0]["message"]["content"]
            else:
                STATS[idx]["errors"] += 1
                return None
    except Exception:
        STATS[idx]["errors"] += 1
        return None


def _pick_key():
    best = min(range(4), key=lambda i: STATS[i]["calls"])
    return best


async def ask(message: str, task: str = "chat", model: str = None, temp: float = 0.3) -> Optional[str]:
    global MODEL_IDX
    candidates = TASK_MODELS.get(task, TASK_MODELS["chat"])
    use_model = model or candidates[MODEL_IDX % len(candidates)]
    MODEL_IDX += 1

    key = _pick_key()
    result = await _call(key, use_model, [{"role": "user", "content": message}], temp)
    if result:
        return result

    for offset in range(1, 4):
        alt = (key + offset) % 4
        result = await _call(alt, use_model, [{"role": "user", "content": message}], temp)
        if result:
            return result
    return None


async def ask_multi(messages: list, task: str = "chat", model: str = None, temp: float = 0.3) -> Optional[str]:
    global MODEL_IDX
    candidates = TASK_MODELS.get(task, TASK_MODELS["chat"])
    use_model = model or candidates[MODEL_IDX % len(candidates)]
    MODEL_IDX += 1

    key = _pick_key()
    result = await _call(key, use_model, messages, temp)
    if result:
        return result

    for offset in range(1, 4):
        alt = (key + offset) % 4
        result = await _call(alt, use_model, messages, temp)
        if result:
            return result
    return None


async def analyze_code(code: str, question: str = "Analyze this code") -> Optional[str]:
    messages = [
        {"role": "system", "content": "You are a code analysis expert. Analyze code and provide detailed insights."},
        {"role": "user", "content": f"{question}\n\n```python\n{code}\n```\n\nProvide detailed analysis including: what it does, bugs, improvements, complexity."},
    ]
    return await ask_multi(messages, task="code", temp=0.1)


async def parallel_tasks(tasks: list[dict]) -> list:
    async def one(t):
        return {"task": t.get("name", "?"), "result": await ask(t["message"], task=t.get("task", "chat"), model=t.get("model"), temp=t.get("temp", 0.3))}
    return await asyncio.gather(*[one(t) for t in tasks])


def print_stats():
    total_calls = sum(s["calls"] for s in STATS)
    total_errors = sum(s["errors"] for s in STATS)
    print(f"  Łączne wywołania: {total_calls} | Błędy: {total_errors}")
    for i, s in enumerate(STATS):
        print(f"  Key{i+1}: {s['calls']} wywołań, {s['errors']} błędów")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════╗
║  Beta AI Groq Multi-Key Accelerator              ║
║  4 klucze, 4 modele, ~120 RPM łącznie            ║
║  Wpisz 'help' aby zobaczyć komendy               ║
╚══════════════════════════════════════════════════╝
""")

    async def main():
        while True:
            try:
                inp = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nDo widzenia!")
                break

            if not inp:
                continue
            if inp in ("help", "h"):
                print("  /chat <tekst>  - rozmowa")
                print("  /code <kod>    - analiza kodu")
                print("  /creative <temat> - pisanie kreatywne")
                print("  /reason <pytanie> - rozumowanie")
                print("  /stats         - statystyki")
                print("  /exit          - wyjdź")
                continue
            if inp in ("exit", "quit", "q"):
                print("Do widzenia!")
                break
            if inp == "/stats":
                print_stats()
                continue

            if inp.startswith("/chat "):
                msg = inp[6:]
                r = await ask(msg, "chat")
            elif inp.startswith("/code "):
                r = await analyze_code(inp[6:])
            elif inp.startswith("/creative "):
                r = await ask(inp[10:], "creative", temp=0.7)
            elif inp.startswith("/reason "):
                r = await ask(inp[8:], "reasoning")
            else:
                r = await ask(inp, "chat")

            if r:
                print(f"\n{r}\n")
            else:
                print("  Brak odpowiedzi z wszystkich kluczy.")

    asyncio.run(main())
