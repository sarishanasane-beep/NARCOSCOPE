"""Near-duplicate detection foundation.

Exact duplicates are detected by SHA-256 at upload time. This module
provides the foundation for future near-duplicate detection using
extracted-text similarity (token-set Jaccard over normalized tokens).
"""

from __future__ import annotations

import re

from app.utils.text import collapse_whitespace

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(collapse_whitespace(text or ""))]


def text_similarity(a: str, b: str) -> float:
    """Jaccard similarity over token sets (0.0 – 1.0)."""
    tokens_a = set(tokenize(a))
    tokens_b = set(tokenize(b))
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(tokens_a & tokens_b) / len(union)


def is_near_duplicate(a: str, b: str, threshold: float = 0.9) -> bool:
    return text_similarity(a, b) >= threshold
