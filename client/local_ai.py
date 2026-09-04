from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_local_llm = None
_model_loaded = False
_model_path = None


def _get_model_path() -> Optional[str]:
    custom = os.environ.get("LOCAL_AI_MODEL", "")
    if custom and os.path.exists(custom):
        return custom

    search_dirs = [
        Path.home() / ".local" / "models",
        Path.home() / "models",
        Path("./models"),
        Path("/tmp/models"),
    ]
    for d in search_dirs:
        if d.exists():
            for f in sorted(d.glob("*.gguf"), key=lambda p: p.stat().st_size):
                return str(f)
    return None


def _is_complex_request(message: str, file_context: str = "") -> bool:
    if file_context and len(file_context) > 500:
        return True
    if len(message) > 300:
        return True
    keywords = [
        "analyze", "compare", "explain", "summarize", "review",
        "rozbierz", "porownaj", "wyjasnij", "podsumuj",
        "optimize", "improve", "refactor", "debug", "fix",
        "what are", "how does", "why", "difference",
    ]
    msg_lower = message.lower()
    if any(w in msg_lower for w in keywords):
        return True
    if message.count("?") >= 2:
        return True
    return False


def _extract_context_summary(message: str, file_context: str = "") -> str:
    parts = []
    if file_context:
        lines = file_context.strip().split("\n")
        key_lines = []
        for line in lines[:50]:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("//"):
                key_lines.append(line)
        if key_lines:
            parts.append("File context: " + " | ".join(key_lines[:10]))

    sentences = re.split(r'[.!?]+', message)
    important = [s.strip() for s in sentences if len(s.strip()) > 15][:5]
    if important:
        parts.append("Key points: " + "; ".join(important))

    return "\n".join(parts) if parts else ""


async def _load_model() -> bool:
    global _local_llm, _model_loaded, _model_path

    if _model_loaded:
        return _local_llm is not None

    _model_loaded = True

    if os.environ.get("LOCAL_AI_ENABLED", "false").lower() != "true":
        logger.info("Local AI disabled (LOCAL_AI_ENABLED != true)")
        return False

    model_path = _get_model_path()
    if not model_path:
        logger.warning("No GGUF model found. Set LOCAL_AI_MODEL=path/to/model.gguf")
        return False

    try:
        from llama_cpp import Llama
        n_ctx = int(os.environ.get("LOCAL_AI_CONTEXT", "2048"))
        n_threads = int(os.environ.get("LOCAL_AI_THREADS", "2"))
        _local_llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=0,
            verbose=False,
        )
        _model_path = model_path
        logger.info("Local AI loaded: %s (ctx=%d, threads=%d)", model_path, n_ctx, n_threads)
        return True
    except ImportError:
        logger.warning("llama-cpp-python not installed. Run: pip install llama-cpp-python")
        return False
    except Exception as e:
        logger.error("Failed to load local model: %s", e)
        return False


def _preprocess_prompt(message: str, file_context: str = "") -> str:
    if not _local_llm:
        return message

    max_tokens = int(os.environ.get("LOCAL_AI_MAX_TOKENS", "256"))

    context_summary = _extract_context_summary(message, file_context)

    system_prompt = """You are a prompt preprocessor. Improve user prompts for an AI assistant.
Rules:
1. Keep original intent
2. Add relevant context from files if provided
3. Structure the request clearly
4. Do NOT change the core question
5. Output ONLY the improved prompt
6. Keep it concise (under 500 words)
7. Include key technical terms from original"""

    user_prompt = f"Improve this prompt for an AI:\n\n{message}"
    if context_summary:
        user_prompt = f"Context:\n{context_summary}\n\nOriginal:\n{message}\n\nImproved:"

    try:
        response = _local_llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            top_p=0.9,
        )
        improved = response["choices"][0]["message"]["content"].strip()
        if improved and len(improved) > 20:
            return improved
    except Exception as e:
        logger.warning("Local AI preprocessing failed: %s", e)

    return message


def preprocess_prompt(message: str, file_context: str = "") -> tuple[str, str]:
    """Returns (original_message, processed_context_or_empty)"""
    if not _is_complex_request(message, file_context):
        return message, ""

    if not _model_loaded:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _load_model())
                    future.result(timeout=5)
            else:
                loop.run_until_complete(_load_model())
        except Exception:
            pass

    if not _local_llm:
        return message, ""

    processed = _preprocess_prompt(message, file_context)
    if processed != message:
        return message, processed
    return message, ""


async def preprocess_prompt_async(message: str, file_context: str = "") -> tuple[str, str]:
    """Async version. Returns (original_message, processed_context_or_empty)"""
    if not _is_complex_request(message, file_context):
        return message, ""

    if not _model_loaded:
        await _load_model()

    if not _local_llm:
        return message, ""

    processed = _preprocess_prompt(message, file_context)
    if processed != message:
        return message, processed
    return message, ""


def is_local_ai_available() -> bool:
    return _local_llm is not None


def get_status() -> dict:
    return {
        "enabled": os.environ.get("LOCAL_AI_ENABLED", "false").lower() == "true",
        "loaded": _local_llm is not None,
        "model_path": _model_path,
        "context_size": int(os.environ.get("LOCAL_AI_CONTEXT", "2048")),
        "max_tokens": int(os.environ.get("LOCAL_AI_MAX_TOKENS", "256")),
    }
