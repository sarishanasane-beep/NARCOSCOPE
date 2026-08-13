"""Test fixtures.

Environment variables are set BEFORE the app is imported so the single
settings singleton and engine bind to an isolated temporary database.
All tests run with AI_ENABLED=false.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_TMP = tempfile.mkdtemp(prefix="narcoscope_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["UPLOAD_DIRECTORY"] = os.path.join(_TMP, "documents")
os.environ["AI_ENABLED"] = "false"
os.environ["AI_PROVIDER"] = ""
os.environ["AI_API_KEY"] = ""
os.environ["PROCESS_ON_UPLOAD"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _truncate_all() -> None:
    from app.database.session import SessionLocal
    from app.models.audit import AuditLog
    from app.models.bookmark import Bookmark
    from app.models.candidate import Candidate
    from app.models.case import Case
    from app.models.claim import Claim
    from app.models.document import Document
    from app.models.entity import Entity
    from app.models.event import Event
    from app.models.evidence import Evidence
    from app.models.fact import Fact
    from app.models.graph_change import GraphChange
    from app.models.graph_snapshot import GraphSnapshot
    from app.models.investigator_note import InvestigatorNote
    from app.models.location import Location
    from app.models.organization import Organization
    from app.models.person import Person
    from app.models.relationship import Relationship
    from app.models.saved_search import SavedSearch
    from app.models.source import Source
    from app.models.workspace import Workspace

    with SessionLocal() as db:
        for model in (
            Candidate,
            Fact,
            Relationship,
            Claim,
            # events/entities now reference evidence and documents (direct
            # source-document FKs), so they must be deleted before those
            # tables. Order: Relationship -> Event/Entity -> Evidence ->
            # Document -> Source.
            Event,
            Person,
            Organization,
            Location,
            Entity,
            Evidence,
            Document,
            Source,
            Case,
            AuditLog,
            # Part 3 tables: children before parents (SQLite FK enforcement
            # is ON). graph_changes.snapshot_id references graph_snapshots,
            # so changes must be deleted first.
            GraphChange,
            GraphSnapshot,
            Workspace,
            Bookmark,
            InvestigatorNote,
            SavedSearch,
        ):
            db.query(model).delete()
        db.commit()


@pytest.fixture(autouse=True)
def _clean_db():
    from app.database.init_db import init_db

    init_db()
    _truncate_all()
    yield
    _truncate_all()


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db():
    from app.database.session import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Helpers for building small test documents
# ---------------------------------------------------------------------------

SAMPLE_TXT = (
    "DEMO DATA test. Arjun Mehta was arrested during Operation Bluewater in "
    "Mumbai on 15 June 2026. The case number is NCB/MUM/123/2026."
)


def make_txt_bytes(text: str = SAMPLE_TXT) -> bytes:
    return text.encode("utf-8")


def make_pdf_bytes(text: str = SAMPLE_TXT) -> bytes:
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    data = pdf.tobytes()
    pdf.close()
    return data


def make_docx_bytes(text: str = SAMPLE_TXT) -> bytes:
    import io

    from docx import Document as DocxDocument

    doc = DocxDocument()
    for paragraph in text.splitlines():
        doc.add_paragraph(paragraph)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def upload_bytes(client, filename: str, data: bytes, mime: str = "text/plain", **extra):
    return client.post(
        "/documents/upload",
        files={"file": (filename, data, mime)},
        data=extra,
    )
