from __future__ import annotations

from segretario.config.settings import LLMSettings
from segretario.connectors.ollama_client import OllamaClient


def build_local_llm(settings: LLMSettings) -> OllamaClient:
    if settings.provider != "ollama":
        raise ValueError(f"unsupported local LLM provider: {settings.provider}")
    return OllamaClient(
        model=settings.model,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
    )
