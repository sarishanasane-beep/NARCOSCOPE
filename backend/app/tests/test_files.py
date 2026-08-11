"""FILE TESTS: uploads, invalid extension, oversized file, duplicates."""

from pathlib import Path

from app.config.settings import settings
from app.tests.conftest import (
    make_docx_bytes,
    make_pdf_bytes,
    make_txt_bytes,
    upload_bytes,
)


def test_upload_txt(client):
    response = upload_bytes(client, "report.txt", make_txt_bytes())
    assert response.status_code == 201
    body = response.json()
    assert body["duplicate_of"] is None
    document = body["document"]
    assert document["file_type"] == "txt"
    assert document["mime_type"] == "text/plain"
    assert len(document["sha256_hash"]) == 64
    assert document["processing_status"] in ("PROCESSED", "REVIEW_REQUIRED")
    assert Path(document["storage_path"]).exists()
    assert "Duplicate" not in body["message"]


def test_upload_pdf(client):
    response = upload_bytes(
        client, "report.pdf", make_pdf_bytes(), mime="application/pdf"
    )
    assert response.status_code == 201
    document = response.json()["document"]
    assert document["file_type"] == "pdf"
    assert document["mime_type"] == "application/pdf"


def test_upload_docx(client):
    response = upload_bytes(
        client,
        "report.docx",
        make_docx_bytes(),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert response.status_code == 201
    document = response.json()["document"]
    assert document["file_type"] == "docx"


def test_invalid_extension(client):
    response = upload_bytes(client, "notes.csv", b"a,b,c\n1,2,3\n", mime="text/csv")
    assert response.status_code == 415
    assert "PDF, DOCX and TXT" in response.json()["detail"]


def test_extension_content_mismatch(client):
    # A PDF renamed to .txt must be rejected.
    response = upload_bytes(client, "sneaky.txt", make_pdf_bytes(), mime="text/plain")
    assert response.status_code == 415


def test_oversized_file(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size", 10)
    response = upload_bytes(client, "big.txt", make_txt_bytes())
    assert response.status_code == 413
    assert "size" in response.json()["detail"].lower()


def test_duplicate_file(client):
    first = upload_bytes(client, "same.txt", make_txt_bytes())
    assert first.status_code == 201
    second = upload_bytes(client, "same_again.txt", make_txt_bytes())
    assert second.status_code == 201
    body = second.json()
    assert body["duplicate_of"] is not None
    assert "Duplicate document detected" in body["message"]
    # The duplicate is never processed as new evidence.
    assert body["document"]["processing_status"] == "DUPLICATE"


def test_original_file_is_preserved(client):
    data = make_txt_bytes("Preserve me. Arjun Mehta was arrested in Mumbai.")
    response = upload_bytes(client, "keep.txt", data)
    assert response.status_code == 201
    storage_path = Path(response.json()["document"]["storage_path"])
    assert storage_path.read_bytes() == data
