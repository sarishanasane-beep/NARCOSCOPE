"""Text normalization helpers shared across services."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")

# Honorifics / titles stripped from the front of person names.
TITLES = [
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "prof.",
    "shri",
    "smt.",
    "inspector",
    "sub-inspector",
    "psi",
    "asi",
    "pi",
    "acp",
    "dcp",
    "commissioner",
    "additional commissioner",
    "assistant commissioner",
    "advocate",
    "judge",
    "constable",
    "head constable",
]

_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def collapse_whitespace(text: str) -> str:
    return _WS.sub(" ", normalize_unicode(text or "")).strip()


def strip_titles(name: str) -> str:
    n = (name or "").strip()
    lower = n.lower()
    for title in sorted(TITLES, key=len, reverse=True):
        if lower == title or lower.startswith(title + " "):
            n = n[len(title) :].strip()
            lower = n.lower()
    return n


def normalize_name(name: str) -> str:
    """Normalize a person/org/location name for comparison.

    Lower-cases, strips honorifics, removes parentheses content and stray
    punctuation, collapses whitespace, drops leading articles.
    """
    if not name:
        return ""
    n = normalize_unicode(name)
    n = strip_titles(n)
    n = _PAREN_RE.sub(" ", n)
    n = n.replace(".", " ")
    n = re.sub(r"[,\u2019'\"\\[\\]{};:]+", " ", n)
    n = _WS.sub(" ", n).strip()
    n = _ARTICLE_RE.sub("", n)
    return _WS.sub(" ", n).strip().lower()


def normalize_case_number(value: str) -> str:
    """Normalize a case reference for exact comparison.

    ``NCB/MUM/123/2026`` and ``ncb/mum/123/2026`` compare equal; spaces are
    stripped so ``FIR 456/2026`` == ``FIR456/2026``.
    """
    if not value:
        return ""
    n = normalize_unicode(value).strip()
    n = _WS.sub("", n)
    return n.upper()
