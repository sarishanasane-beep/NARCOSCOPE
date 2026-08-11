"""Character spans inside the cleaned document text."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextSpan:
    start: int
    end: int
    text: str

    @property
    def length(self) -> int:
        return self.end - self.start
