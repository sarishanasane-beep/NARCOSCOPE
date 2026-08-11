"""AI provider abstraction.

AI is OPTIONAL. Every provider implements the same interface. AI output
ALWAYS enters the candidate layer first — it can never directly modify
trusted data, confirm people/relationships, merge entities, or determine
guilt.

Phase 1 ships the ``NoneProvider`` (deterministic mode). Future
providers (Gemini, OpenAI) must follow this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIExtractionSuggestion:
    """AI-proposed extraction output (always candidate-only)."""

    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    notes: str | None = None


class AIProvider(ABC):
    """Interface every AI provider implements."""

    name: str = "base"
    enabled: bool = False

    @abstractmethod
    def extract_entities(self, text: str) -> AIExtractionSuggestion | None:
        """Propose entities/relationships for review (never auto-confirm)."""

    @abstractmethod
    def summarize(self, text: str) -> str | None:
        """Summarize already-verified information (optional)."""

    @abstractmethod
    def health(self) -> dict:
        """Provider status for the /health endpoint."""
