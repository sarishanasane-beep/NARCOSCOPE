"""AI provider implementations.

Phase 1: ``NoneProvider`` keeps the application fully functional in
deterministic mode. Gemini/OpenAI providers expose the interface; when
configured but not implemented, the service falls back to
``NoneProvider`` and logs the limitation.
"""

from __future__ import annotations

from app.services.ai.base import AIExtractionSuggestion, AIProvider
from app.utils.logging import log_event

import logging

logger = logging.getLogger(__name__)


class NoneProvider(AIProvider):
    """The default provider: deterministic-only mode."""

    name = "none"
    enabled = False

    def extract_entities(self, text: str) -> AIExtractionSuggestion | None:
        return None

    def summarize(self, text: str) -> str | None:
        return None

    def health(self) -> dict:
        return {"provider": self.name, "enabled": False}


class GeminiProvider(AIProvider):
    """Google Gemini provider — interface only (not implemented in Phase 1)."""

    name = "gemini"
    enabled = True

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def extract_entities(self, text: str) -> AIExtractionSuggestion | None:
        raise NotImplementedError("GeminiProvider is not implemented in Phase 1.")

    def summarize(self, text: str) -> str | None:
        raise NotImplementedError("GeminiProvider is not implemented in Phase 1.")

    def health(self) -> dict:
        return {"provider": self.name, "enabled": True, "implemented": False}


class OpenAIProvider(AIProvider):
    """OpenAI provider — interface only (not implemented in Phase 1)."""

    name = "openai"
    enabled = True

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def extract_entities(self, text: str) -> AIExtractionSuggestion | None:
        raise NotImplementedError("OpenAIProvider is not implemented in Phase 1.")

    def summarize(self, text: str) -> str | None:
        raise NotImplementedError("OpenAIProvider is not implemented in Phase 1.")

    def health(self) -> dict:
        return {"provider": self.name, "enabled": True, "implemented": False}
