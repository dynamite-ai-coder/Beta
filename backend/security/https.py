from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse


async def https_redirect_middleware(
    request: Request, call_next
):
    if request.headers.get("x-forwarded-proto") == "http":
        url = request.url.replace(scheme="https")
        return RedirectResponse(
            url=url, status_code=301
        )
    return await call_next(request)
