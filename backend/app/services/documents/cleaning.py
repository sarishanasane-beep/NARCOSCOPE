"""Text cleaning.

Normalizes excessive whitespace, removes obvious extraction artifacts and
normalizes Unicode safely. Paragraph and page boundaries are preserved
where possible. The source text is NOT aggressively modified — the raw
extracted text is always available (see ``documents.extracted_text`` on
the raw side is the cleaned copy; the original file itself is untouched).
"""

from __future__ import annotations

import re
import unicodedata

from app.services.documents.segments import PageSegment, page_for_offset

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES_RE = re.compile(r"[ \t]{2,}")
_NEWLINES_RE = re.compile(r"\n{3,}")
_PUNCT_SPACE_RE = re.compile(r"\s+([.,;:!?])")
_PAGE_SEP = "\n\n"


def clean_page_text(raw: str) -> str:
    text = raw or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = _CTRL_RE.sub("", text)
    text = text.replace("\u2028", "\n").replace("\u2029", "\n")
    text = _NEWLINES_RE.sub("\n\n", text)
    text = _SPACES_RE.sub(" ", text)
    text = _PUNCT_SPACE_RE.sub(r"\1", text)
    return text.strip()


def build_clean_document(pages: list[tuple[int, str]]) -> tuple[str, list[PageSegment]]:
    """Concatenate cleaned pages into one text with page offset segments."""
    parts: list[str] = []
    segments: list[PageSegment] = []
    offset = 0
    for page_number, raw in pages:
        cleaned = clean_page_text(raw)
        if cleaned:
            segments.append(PageSegment(page_number=page_number, start=offset, end=offset + len(cleaned)))
            parts.append(cleaned)
            offset += len(cleaned)
        # Preserve a paragraph-like boundary between pages.
        parts.append(_PAGE_SEP)
        offset += len(_PAGE_SEP)
    full_text = "".join(parts).rstrip(_PAGE_SEP)
    return full_text, segments
