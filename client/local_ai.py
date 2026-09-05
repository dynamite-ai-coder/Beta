from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_local_llm = None
_model_loaded = False
_model_path = None
_env_info: dict | None = None

RECOMMENDED_MODELS = {
    "termux_small": {
        "name": "TinyLlama 1.1B Q4_K_M",
        "url": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "filename": "tinyllama-1.1b-chat-q4_k_m.gguf",
        "size_mb": 637,
        "ram_needed_mb": 1500,
        "n_ctx": 1024,
        "n_threads": 2,
    },
    "termux_medium": {
        "name": "Phi-2 Q4_K_M",
        "url": "https://huggingface.co/TheBloke/phi-2-GGUF/resolve/main/phi-2.Q4_K_M.gguf",
        "filename": "phi-2-q4_k_m.gguf",
        "size_mb": 1100,
        "ram_needed_mb": 2500,
        "n_ctx": 2048,
        "n_threads": 2,
    },
    "termux_large": {
        "name": "Gemma 2B Q4_K_M",
        "url": "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
        "filename": "gemma-2b-it-q4_k_m.gguf",
        "size_mb": 1500,
        "ram_needed_mb": 3000,
        "n_ctx": 2048,
        "n_threads": 2,
    },
    "desktop_small": {
        "name": "Llama 3.2 3B Q4_K_M",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "filename": "llama-3.2-3b-instruct-q4_k_m.gguf",
        "size_mb": 1700,
        "ram_needed_mb": 3500,
        "n_ctx": 2048,
        "n_threads": 4,
    },
    "desktop_medium": {
        "name": "Mistral 7B Q4_K_M",
        "url": "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        "filename": "mistral-7b-instruct-q4_k_m.gguf",
        "size_mb": 3800,
        "ram_needed_mb": 6000,
        "n_ctx": 4096,
        "n_threads": 6,
    },
}


def detect_environment() -> dict:
    global _env_info
    if _env_info:
        return _env_info

    is_termux = False
    is_android = False
    is_windows = sys.platform == "win32"
    is_linux = sys.platform == "linux"
    ram_mb = 0

    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram_mb = int(line.split()[1]) // 1024
                        break
    except Exception:
        pass

    if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
        is_termux = True
        is_android = True
    elif os.path.exists("/system/build.prop"):
        is_android = True

    if not ram_mb and is_windows:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong)]
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            ram_mb = mem.ullTotalPhys // (1024 * 1024)
        except Exception:
            ram_mb = 8192

    if not ram_mb:
        ram_mb = 4096

    if is_termux or (is_android and ram_mb < 6000):
        if ram_mb < 3000:
            recommended = "termux_small"
        elif ram_mb < 5000:
            recommended = "termux_medium"
        else:
            recommended = "termux_large"
    else:
        if ram_mb < 8000:
            recommended = "desktop_small"
        else:
            recommended = "desktop_medium"

    _env_info = {
        "platform": "termux" if is_termux else ("android" if is_android else ("windows" if is_windows else "linux")),
        "is_termux": is_termux,
        "is_android": is_android,
        "is_windows": is_windows,
        "is_linux": is_linux,
        "ram_mb": ram_mb,
        "recommended_model": recommended,
        "recommended_config": RECOMMENDED_MODELS[recommended],
    }

    logger.info("Environment: %s | RAM: %dMB | Recommended: %s",
                _env_info["platform"], ram_mb, recommended)
    return _env_info


def _get_model_path() -> Optional[str]:
    custom = os.environ.get("LOCAL_AI_MODEL", "")
    if custom and os.path.exists(custom):
        return custom

    env = detect_environment()
    rec = env["recommended_config"]
    models_dir = Path.home() / ".local" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    expected = models_dir / rec["filename"]
    if expected.exists():
        return str(expected)

    search_dirs = [
        models_dir,
        Path.home() / "models",
        Path("./models"),
        Path("/tmp/models"),
    ]
    for d in search_dirs:
        if d.exists():
            for f in sorted(d.glob("*.gguf"), key=lambda p: p.stat().st_size):
                return str(f)
    return None


async def _download_model() -> Optional[str]:
    env = detect_environment()
    rec = env["recommended_config"]
    models_dir = Path.home() / ".local" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / rec["filename"]

    if target.exists():
        return str(target)

    logger.info("Downloading %s (%dMB) to %s...", rec["name"], rec["size_mb"], target)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            async with client.stream("GET", rec["url"]) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(target, "wb") as f:
                    async for chunk in r.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total and downloaded % (1024 * 1024) == 0:
                            pct = (downloaded / total) * 100
                            logger.info("Download: %d/%dMB (%.0f%%)", downloaded // (1024*1024), total // (1024*1024), pct)

        logger.info("Model downloaded: %s (%dMB)", target, target.stat().st_size // (1024*1024))
        return str(target)
    except Exception as e:
        logger.error("Download failed: %s", e)
        if target.exists():
            target.unlink()
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
        "create", "write", "generate", "build", "design",
        "find", "search", "lookup", "research",
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
        logger.info("No GGUF model found. Auto-downloading recommended model...")
        model_path = await _download_model()
        if not model_path:
            logger.warning("No model available. Set LOCAL_AI_MODEL=path/to/model.gguf")
            return False

    env = detect_environment()
    rec = env["recommended_config"]
    n_ctx = int(os.environ.get("LOCAL_AI_CONTEXT", str(rec["n_ctx"])))
    n_threads = int(os.environ.get("LOCAL_AI_THREADS", str(rec["n_threads"])))

    try:
        from llama_cpp import Llama
        _local_llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=0,
            verbose=False,
        )
        _model_path = model_path
        logger.info("Local AI loaded: %s (ctx=%d, threads=%d, env=%s)",
                     Path(model_path).name, n_ctx, n_threads, env["platform"])
        return True
    except ImportError:
        logger.warning("llama-cpp-python not installed. Run: pip install llama-cpp-python")
        return False
    except Exception as e:
        logger.error("Failed to load local model: %s", e)
        return False


async def _cloud_preprocess(message: str, file_context: str = "") -> str:
    api_key = os.environ.get("AI_API_KEY", "")
    if not api_key:
        return ""

    try:
        import httpx as _httpx
        base_url = os.environ.get("AI_BASE_URL", "https://api.groq.com/openai/v1")
        model = os.environ.get("AI_MODEL", "llama-3.1-8b-instant")

        system = (
            "You are a prompt preprocessor. Improve this user prompt for an AI assistant.\n"
            "Rules: keep original intent, add relevant context, structure clearly, "
            "output ONLY the improved prompt, keep concise (under 300 words)."
        )

        user_prompt = f"Improve this prompt:\n\n{message}"
        if file_context:
            lines = [l.strip() for l in file_context.strip().split("\n") if l.strip()][:10]
            user_prompt = f"File context: {' | '.join(lines)}\n\n{message}\n\nImproved:"

        async with _httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
                    "max_tokens": 512,
                    "temperature": 0.3,
                },
            )
            r.raise_for_status()
            improved = r.json()["choices"][0]["message"]["content"].strip()
            if improved and len(improved) > 20:
                return improved
    except Exception as e:
        logger.debug("Cloud preprocessing failed: %s", e)
    return ""


def _preprocess_prompt(message: str, file_context: str = "") -> str:
    if not _local_llm:
        return message

    env = detect_environment()
    rec = env["recommended_config"]
    max_tokens = int(os.environ.get("LOCAL_AI_MAX_TOKENS", "256"))

    context_summary = _extract_context_summary(message, file_context)

    system_prompt = """You are a prompt preprocessor. Improve user prompts for an AI assistant.
Rules:
1. Keep original intent exactly
2. Add relevant context from files if provided
3. Structure the request clearly with specific requirements
4. Do NOT change the core question or add restrictions
5. Output ONLY the improved prompt
6. Keep it concise (under 500 words)
7. Include key technical terms from original
8. Add specific details that help the AI give a better answer"""

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
        import concurrent.futures
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _load_model())
                    future.result(timeout=5)
            else:
                loop.run_until_complete(_load_model())
        except Exception:
            pass

    if _local_llm:
        processed = _preprocess_prompt(message, file_context)
        if processed != message:
            return message, processed
        return message, ""

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _cloud_preprocess(message, file_context))
                result = future.result(timeout=15)
        else:
            result = loop.run_until_complete(_cloud_preprocess(message, file_context))
        if result and result != message:
            return message, result
    except Exception:
        pass

    return message, ""


async def preprocess_prompt_async(message: str, file_context: str = "") -> tuple[str, str]:
    """Async version. Returns (original_message, processed_context_or_empty)"""
    if not _is_complex_request(message, file_context):
        return message, ""

    if not _model_loaded:
        await _load_model()

    if _local_llm:
        processed = _preprocess_prompt(message, file_context)
        if processed != message:
            return message, processed
        return message, ""

    result = await _cloud_preprocess(message, file_context)
    if result and result != message:
        return message, result
    return message, ""


def is_local_ai_available() -> bool:
    return _local_llm is not None


def get_status() -> dict:
    env = detect_environment()
    rec = env["recommended_config"]
    model_path = _get_model_path()

    groq_key = os.environ.get("AI_API_KEY", "")

    return {
        "enabled": os.environ.get("LOCAL_AI_ENABLED", "false").lower() == "true",
        "loaded": _local_llm is not None,
        "model_path": _model_path or model_path,
        "model_name": rec["name"],
        "model_size_mb": rec["size_mb"],
        "environment": env["platform"],
        "ram_mb": env["ram_mb"],
        "recommended_model": env["recommended_model"],
        "context_size": int(os.environ.get("LOCAL_AI_CONTEXT", str(rec["n_ctx"]))),
        "max_tokens": int(os.environ.get("LOCAL_AI_MAX_TOKENS", "256")),
        "threads": int(os.environ.get("LOCAL_AI_THREADS", str(rec["n_threads"]))),
        "groq_configured": bool(groq_key),
        "cloud_preprocessor": "groq" if groq_key else "none",
    }
