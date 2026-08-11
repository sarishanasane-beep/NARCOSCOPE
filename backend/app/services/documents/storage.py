"""Storage helpers for original + extracted documents.

The original uploaded document is NEVER modified. It is stored under
``<upload_directory>/original/<year>/<document_id>.<ext>`` and remains
available for evidence verification.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.config.settings import settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    """Sanitize an untrusted filename (never trust the original name)."""
    name = (filename or "").strip().replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name)
    name = re.sub(r"_{2,}", "_", name).strip("._ ")
    if not name:
        name = "document"
    return name[:180]


def unique_stored_filename(document_id: str, extension: str) -> str:
    return f"{document_id}.{extension.lstrip('.')}"


def save_original_file(data: bytes, document_id: str, extension: str) -> Path:
    """Store the original bytes; returns the absolute storage path."""
    base = Path(settings.upload_directory) / "original" / str(datetime.now().year)
    base.mkdir(parents=True, exist_ok=True)
    stored_name = unique_stored_filename(document_id, extension)
    path = base / stored_name
    path.write_bytes(data)
    return path


def save_extracted_text(document_id: str, text: str) -> Path:
    """Store the cleaned extracted text for inspection."""
    base = Path(settings.upload_directory) / "extracted"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{document_id}.txt"
    path.write_text(text, encoding="utf-8")
    return path
