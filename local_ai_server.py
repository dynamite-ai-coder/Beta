#!/usr/bin/env python3
"""
Beta Local AI Server - Phi-3-mini-4k-instruct with compact protocol
Communicates with MultiAgent backend using Beta AI shared protocol.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared_protocol import (
    MsgType, ProtocolMsg, Complexity,
    pack_preprocess, pack_classify, pack_extract, pack_simplify,
    unpack_preprocess_reply, unpack_classify_reply,
    decode_any, msg_type_name,
)

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


def _llm_generate(system: str, user: str, max_tokens: int = MAX_TOKENS) -> str:
    if not _llm:
        return ""
    try:
        response = _llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            top_p=0.9,
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning("LLM generation failed: %s", e)
        return ""


def _handle_preprocess(payload: dict) -> dict:
    message = payload.get("m", "")
    file_context = payload.get("fc", "")
    lang = payload.get("l", "pl")

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

    t0 = time.time()
    result = _llm_generate(system, user_prompt)
    latency = int((time.time() - t0) * 1000)

    return {
        "p": result,
        "o": message,
        "ok": 1 if result and len(result) > 10 else 0,
        "ms": latency,
    }


def _handle_classify(payload: dict) -> dict:
    message = payload.get("m", "")

    system = (
        "Classify this request by complexity for a multi-agent AI system.\n"
        "Return JSON: {\"cx\":\"simple|medium|complex\",\"ag\":[\"agent1\",...],\"sk\":[\"skip1\",...],\"c\":0.8}\n"
        "Agents: planner, researcher, solver, critic, judge\n"
        "Simple=facts/translations, Medium=analysis, Complex=multi-step research"
    )

    result = _llm_generate(system, f"Classify: {message[:300]}", max_tokens=150)

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        data = __import__("json").loads(cleaned)
        return {
            "cx": data.get("complexity", data.get("cx", "medium")),
            "ag": data.get("agents_needed", data.get("ag", ["solver", "judge"])),
            "sk": data.get("skip", data.get("sk", [])),
            "c": data.get("confidence", data.get("c", 0.7)),
        }
    except Exception:
        return {"cx": "medium", "ag": ["solver", "critic", "judge"], "sk": [], "c": 0.7}


def _handle_extract(payload: dict) -> dict:
    text = payload.get("t", "")
    keys = payload.get("k", ["solution", "answer", "result"])

    system = (
        "Extract key information from this text.\n"
        f"Look for these keys: {', '.join(keys)}\n"
        "Return JSON: {\"e\":{\"key\":\"value\"},\"pt\":\"plain text summary\",\"ok\":1}"
    )

    result = _llm_generate(system, f"Extract from:\n{text[:500]}", max_tokens=200)

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        data = __import__("json").loads(cleaned)
        return {
            "e": data.get("extracted", data.get("e", {})),
            "pt": data.get("plain_text", data.get("pt", result)),
            "ok": 1,
        }
    except Exception:
        return {"e": {}, "pt": result, "ok": 1}


def _handle_simplify(payload: dict) -> dict:
    text = payload.get("t", "")
    max_words = payload.get("w", 100)

    system = (
        f"Simplify this text to under {max_words} words.\n"
        "Keep the core meaning. Be concise and clear.\n"
        "Return ONLY the simplified text."
    )

    result = _llm_generate(system, f"Simplify:\n{text[:500]}", max_tokens=150)

    return {
        "s": result,
        "ow": len(text.split()),
        "sw": len(result.split()) if result else 0,
    }


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
        "protocol": "beta-v1",
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
            return JSONResponse({"error": "Model not loaded"}, status_code=503)

    t0 = time.time()
    result = _handle_preprocess({"m": message, "fc": file_context})
    latency = time.time() - t0

    return JSONResponse({
        "original": result["o"],
        "processed": result["p"],
        "used_local_ai": bool(result["p"]),
        "latency_ms": int(latency * 1000),
    })


@app.post("/v1/classify")
async def classify(request: Request):
    body = await request.json()
    message = body.get("message", "")

    if not message:
        return JSONResponse({"error": "No message"}, status_code=400)

    if not _llm:
        if not _load_model():
            return JSONResponse({"error": "Model not loaded"}, status_code=503)

    result = _handle_classify({"m": message})
    return JSONResponse(result)


@app.post("/v1/extract")
async def extract(request: Request):
    body = await request.json()
    text = body.get("text", "")
    keys = body.get("keys", ["solution", "answer", "result"])

    if not text:
        return JSONResponse({"error": "No text"}, status_code=400)

    if not _llm:
        if not _load_model():
            return JSONResponse({"error": "Model not loaded"}, status_code=503)

    result = _handle_extract({"t": text, "k": keys})
    return JSONResponse(result)


@app.post("/v1/simplify")
async def simplify(request: Request):
    body = await request.json()
    text = body.get("text", "")
    max_words = body.get("max_words", 100)

    if not text:
        return JSONResponse({"error": "No text"}, status_code=400)

    if not _llm:
        if not _load_model():
            return JSONResponse({"error": "Model not loaded"}, status_code=503)

    result = _handle_simplify({"t": text, "w": max_words})
    return JSONResponse(result)


@app.post("/v1/protocol")
async def protocol_endpoint(request: Request):
    body = await request.json()
    raw = body.get("message", "")

    if not raw:
        return JSONResponse({"error": "No message"}, status_code=400)

    if not _llm:
        if not _load_model():
            return JSONResponse({"error": "Model not loaded"}, status_code=503)

    msg = decode_any(raw)
    logger.info("Protocol msg: type=%s", msg_type_name(msg))

    if msg.type == MsgType.PREPROCESS:
        result = _handle_preprocess(msg.payload)
        reply = ProtocolMsg(
            type=MsgType.PREPROCESS_REPLY, src="localai", dst="backend",
            payload=result, ref=msg.id,
        ).encode()
    elif msg.type == MsgType.CLASSIFY:
        result = _handle_classify(msg.payload)
        reply = ProtocolMsg(
            type=MsgType.CLASSIFY_REPLY, src="localai", dst="backend",
            payload=result, ref=msg.id,
        ).encode()
    elif msg.type == MsgType.EXTRACT:
        result = _handle_extract(msg.payload)
        reply = ProtocolMsg(
            type=MsgType.EXTRACT_REPLY, src="localai", dst="backend",
            payload=result, ref=msg.id,
        ).encode()
    elif msg.type == MsgType.SIMPLIFY:
        result = _handle_simplify(msg.payload)
        reply = ProtocolMsg(
            type=MsgType.SIMPLIFY_REPLY, src="localai", dst="backend",
            payload=result, ref=msg.id,
        ).encode()
    elif msg.type == MsgType.PING:
        reply = ProtocolMsg(type=MsgType.PONG, src="localai", dst="backend").encode()
    else:
        return JSONResponse({"error": f"Unknown type: 0x{msg.type:02X}"}, status_code=400)

    return JSONResponse({"reply": reply})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
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
