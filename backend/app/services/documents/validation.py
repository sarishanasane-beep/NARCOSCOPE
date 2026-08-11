"""Upload validation.

V1 accepts ONLY PDF, DOCX and TXT. Files are validated by extension and
content (magic bytes); size is bounded by ``MAX_UPLOAD_SIZE``. Uploaded
files are never executed.
"""

from __future__ import annotations

from app.config.settings import settings
from app.utils.errors import FileTooLargeError, UnsupportedFileError

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}


def _extension_of(filename: str) -> str | None:
    if "." not in filename:
        return None
    return filename.rsplit(".", 1)[-1].lower()


def detect_type_from_content(data: bytes) -> str | None:
    """Return file_type from magic bytes, or None when unrecognized."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "docx"
    # Text: try common encodings (utf-8 with BOM, utf-16 BOM, latin-1).
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            data.decode(encoding)
            return "txt"
        except UnicodeDecodeError:
            continue
    try:
        data.decode("latin-1")
        return "txt"
    except UnicodeDecodeError:
        return None


def validate_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Validate an upload; returns ``(file_type, mime_type)``.

    Raises ``UnsupportedFileError`` or ``FileTooLargeError``.
    """
    extension = _extension_of(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileError(technical=f"extension={extension!r}")

    if len(data) > settings.max_upload_size:
        raise FileTooLargeError(
            technical=f"size={len(data)} max={settings.max_upload_size}"
        )

    content_type = detect_type_from_content(data)
    if content_type is None:
        raise UnsupportedFileError(
            "Unsupported file type. NARCOSCOPE V1 accepts PDF, DOCX and TXT files.",
            technical="magic bytes unrecognized",
        )

    # A recognized content type that contradicts the extension is rejected.
    if extension != content_type:
        raise UnsupportedFileError(
            technical=f"extension={extension} content={content_type}",
        )

    return content_type, MIME_TYPES[content_type]
