from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, Request

from backend.config import settings

logger = logging.getLogger(__name__)

_tokens: dict[str, datetime] = {}


def create_session_token() -> str:
    token = secrets.token_urlsafe(32)
    _tokens[token] = datetime.now(timezone.utc)
    return token


def validate_session_token(token: str) -> bool:
    if token in _tokens:
        created = _tokens[token]
        if datetime.now(timezone.utc) - created < timedelta(seconds=settings.browser_session_timeout):
            return True
        del _tokens[token]
    return False


def cleanup_expired_tokens() -> int:
    now = datetime.now(timezone.utc)
    expired = [t for t, c in _tokens.items() if now - c > timedelta(seconds=settings.browser_session_timeout)]
    for t in expired:
        del _tokens[t]
    return len(expired)


def redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[^\w\-.]', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')
    return name[:100] if name else "unknown"


async def verify_api_key(authorization: str | None = Header(None)) -> None:
    if not settings.api_auth_token:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required")
    if not secrets.compare_digest(token, settings.api_auth_token):
        raise HTTPException(status_code=403, detail="Invalid API token")


_rate_limits: dict[str, list[datetime]] = {}


def check_rate_limit(client_ip: str) -> bool:
    now = datetime.now(timezone.utc)
    window = timedelta(seconds=60)
    if client_ip not in _rate_limits:
        _rate_limits[client_ip] = []
    _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < window]
    if len(_rate_limits[client_ip]) >= settings.rate_limit_per_minute:
        return False
    _rate_limits[client_ip].append(now)
    return True


async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return await call_next(request)
