#!/usr/bin/env python3
"""
Beta Local AI Server - Phi-3-mini-4k-instruct preprocessor
Runs as standalone service, exposes HTTP API for prompt preprocessing.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Beta-LocalAI", docs_url=None, redoc_url=None)
_llm = None
_model_loaded = False
_start_time = time.time()

MODEL_PATH = os.environ.get("LOCAL_AI_MODEL", "/app/models/phi-3-mini-4k-instruct-q4_k_m.gguf")
N_CTX = int(os.environ.get("LOCAL_AI_CONTEXT", "4096"))
N_THREADS = int(os.environ.get("LOCAL_AI_THREADS", "4"))
MAX_TOKENS = int(os.environ.get("LOCAL_AI_MAX_TOKENS", "512"))


def _load_model():
    global _llm, _model_loaded
    if _model_loaded:
        return _llm is not None
    _model_loaded = True

    if not os.path.exists(MODEL_PATH):
        logger.error("Model not found: %s", MODEL_PATH)
        return False

    try:
        from llama_cpp import Llama
        logger.info("Loading model: %s (ctx=%d, threads=%d)", MODEL_PATH, N_CTX, N_THREADS)
        t0 = time.time()
        _llm = Llama(
            model_path=MODEL_PATH,
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            n_gpu_layers=0,
            verbose=False,
        )
        logger.info("Model loaded in %.1fs", time.time() - t0)
        return True
    except ImportError:
        logger.error("llama-cpp-python not installed")
        return False
    except Exception as e:
        logger.error("Failed to load model: %s", e)
        return False


def _preprocess(message: str, file_context: str = "") -> str:
    if not _llm:
        return ""

    system = (
        "You are a prompt preprocessor. Improve user prompts for an AI assistant.\n"
        "Rules:\n"
        "1. Keep original intent exactly\n"
        "2. Add relevant context from files if provided\n"
        "3. Structure the request clearly\n"
        "4. Output ONLY the improved prompt\n"
        "5. Keep concise (under 300 words)\n"
        "6. Include key technical terms from original"
    )

    user_prompt = f"Improve this prompt for an AI:\n\n{message}"
    if file_context:
        lines = [l.strip() for l in file_context.strip().split("\n") if l.strip()][:10]
        user_prompt = f"Context: {' | '.join(lines)}\n\n{message}\n\nImproved:"

    try:
        response = _llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=MAX_TOKENS,
            temperature=0.3,
            top_p=0.9,
        )
        result = response["choices"][0]["message"]["content"].strip()
        if result and len(result) > 20:
            return result
    except Exception as e:
        logger.warning("Preprocessing failed: %s", e)
    return ""


@app.on_event("startup")
async def startup():
    _load_model()


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "model_loaded": _llm is not None,
        "model_path": MODEL_PATH,
        "model_name": "Phi-3-mini-4k-instruct",
        "uptime": int(time.time() - _start_time),
    })


@app.post("/v1/preprocess")
async def preprocess(request: Request):
    body = await request.json()
    message = body.get("message", "")
    file_context = body.get("file_context", "")

    if not message:
        return JSONResponse({"error": "No message"}, status_code=400)

    if not _llm:
        if not _load_model():
            return JSONResponse({"error": "Model not loaded", "processed": ""}, status_code=503)

    t0 = time.time()
    processed = _preprocess(message, file_context)
    latency = time.time() - t0

    return JSONResponse({
        "original": message,
        "processed": processed,
        "used_local_ai": bool(processed),
        "latency_ms": int(latency * 1000),
    })


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible endpoint for simple chat."""
    body = await request.json()
    messages = body.get("messages", [])

    if not messages:
        return JSONResponse({"error": "No messages"}, status_code=400)

    if not _llm:
        if not _load_model():
            return JSONResponse({"error": "Model not loaded"}, status_code=503)

    try:
        response = _llm.create_chat_completion(
            messages=messages,
            max_tokens=body.get("max_tokens", MAX_TOKENS),
            temperature=body.get("temperature", 0.3),
        )
        return JSONResponse(response)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    port = int(os.environ.get("LOCAL_AI_PORT", "8100"))
    logger.info("Beta Local AI Server starting on port %d...", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
