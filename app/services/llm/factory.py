from __future__ import annotations

from app.core.config import Settings
from app.services.llm.base import LLMProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.openai_provider import OpenAILLMProvider


def get_llm_provider(settings: Settings) -> LLMProvider:
    """설정에 따라 LLM provider를 고름

    - llm_provider="mock" → 항상 규칙 기반 Mock
    - llm_provider="openai" → 항상 OpenAI
    - llm_provider="auto" → 키 있으면 OpenAI, 없으면 Mock
    """
    mode = settings.llm_provider.lower()
    if mode == "mock":
        return MockLLMProvider()
    if mode == "openai" or (mode == "auto" and settings.openai_api_key):
        return OpenAILLMProvider(
            settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            categories=settings.proofread_categories,
        )
    return MockLLMProvider()
