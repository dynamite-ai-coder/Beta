from __future__ import annotations

from backend.ai.providers import BaseAIProvider, create_provider
from backend.config import settings


def get_ai_provider() -> BaseAIProvider:
    return create_provider(
        provider_type=settings.ai_provider,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        base_url=settings.ai_base_url,
    )
