"""Centralized, human-readable application errors.

Technical details are logged server-side; users only ever see the
``message`` attribute. Never show raw stack traces to normal users.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 400
    message: str = "An error occurred."

    def __init__(self, message: str | None = None, *, technical: str | None = None) -> None:
        self.message = message or self.message
        self.technical = technical
        super().__init__(self.message)


class UnsupportedFileError(AppError):
    status_code = 415
    message = "Unsupported file type. NARCOSCOPE V1 accepts PDF, DOCX and TXT files."


class DuplicateDocumentError(AppError):
    status_code = 409
    message = "Duplicate document detected. This document already exists."


class FileTooLargeError(AppError):
    status_code = 413
    message = "File exceeds the maximum allowed upload size."


class ExtractionError(AppError):
    status_code = 422
    message = "Text extraction failed. Please review the original document."


class NotFoundError(AppError):
    status_code = 404
    message = "Resource not found."


class ValidationError(AppError):
    status_code = 422
    message = "Validation failed."


class CandidateStateError(AppError):
    status_code = 409
    message = "Candidate is not in a reviewable state."


class AIUnavailableError(AppError):
    status_code = 503
    message = "AI assistance is unavailable. Continuing in deterministic mode."
