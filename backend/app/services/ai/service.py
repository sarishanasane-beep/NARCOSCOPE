"""AI service.

Selects a provider from configuration. AI output is ALWAYS treated as
candidate material for human review — never as trusted data.
"""

from __future__ import annotations

from app.config.settings import settings
from app.services.ai.base import AIExtractionSuggestion, AIProvider
from app.services.ai.providers import GeminiProvider, NoneProvider, OpenAIProvider
from app.utils.errors import AIUnavailableError
from app.utils.logging import log_event

import logging

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self) -> None:
        self._provider: AIProvider = self._build_provider()

    def _build_provider(self) -> AIProvider:
        if not settings.ai_enabled:
            return NoneProvider()
        provider_name = (settings.ai_provider or "").lower()
        providers: dict[str, type[AIProvider]] = {
            "gemini": GeminiProvider,
            "openai": OpenAIProvider,
        }
        provider_cls = providers.get(provider_name)
        if provider_cls is None:
            log_event(
                logger, "ai_provider_unavailable",
                provider=provider_name or "unset", reason="falling back to deterministic mode",
            )
            return NoneProvider()
        try:
            return provider_cls(api_key=settings.ai_api_key)
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "ai_provider_init_failed", provider=provider_name, error=str(exc))
            return NoneProvider()

    @property
    def provider(self) -> AIProvider:
        return self._provider

    @property
    def ai_enabled(self) -> bool:
        return self._provider.enabled and settings.ai_enabled

    def enhance(self, text: str) -> AIExtractionSuggestion | None:
        """Optional AI enhancement — output is candidate-only.

        In deterministic mode this returns ``None`` immediately.
        """
        if not self.ai_enabled:
            return None
        try:
            suggestion = self._provider.extract_entities(text)
            if suggestion:
                log_event(logger, "ai_suggestions_produced", provider=self._provider.name)
            return suggestion
        except NotImplementedError:
            log_event(
                logger, "ai_provider_not_implemented",
                provider=self._provider.name, reason="continuing in deterministic mode",
            )
            return None
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "ai_error", provider=self._provider.name, error=str(exc))
            return None

    def health(self) -> dict:
        return self._provider.health()


_ai_service: AIService | None = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
