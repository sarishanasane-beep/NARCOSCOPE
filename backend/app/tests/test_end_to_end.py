"""PHASE 1 ACCEPTANCE — the complete review workflow, no AI required."""

from app.tests.conftest import make_txt_bytes, upload_bytes

TEXT = (
    "DEMO DATA test. Arjun Mehta was arrested during Operation Bluewater in "
    "Mumbai on 15 June 2026. The case number is NCB/MUM/123/2026."
)


def test_full_workflow(client):
    # STEP 3–6: upload, store original, hash, extract
    response = upload_bytes(client, "acceptance.txt", make_txt_bytes(TEXT))
    assert response.status_code == 201
    body = response.json()
    document = body["document"]
    assert body["duplicate_of"] is None
    assert len(document["sha256_hash"]) == 64
    assert document["processing_status"] in ("PROCESSED", "REVIEW_REQUIRED")

    # STEP 7–9: candidates created with supporting evidence
    candidates = client.get("/candidates").json()["items"]
    assert candidates, "expected candidates after processing"
    pending = [c for c in candidates if c["status"] == "PENDING"]
    assert pending
    assert any(c["evidence"] is not None and c["evidence"]["exact_text"] for c in pending)

    entity_candidate = next(
        c for c in pending
        if c["candidate_type"] in ("ENTITY", "LOCATION")
        and c["proposed_data"].get("name") == "Arjun Mehta"
    )

    # STEP 10–11: confirm a candidate -> trusted database
    confirm = client.post(
        f"/candidates/{entity_candidate['candidate_id']}/confirm",
        json={"reviewed_by": "acceptance-test", "reason": "acceptance test"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "CONFIRMED"

    entities = client.get("/entities?entity_type=PERSON").json()["items"]
    assert any(e["canonical_name"] == "Arjun Mehta" for e in entities)

    # STEP 12–13: reject another candidate -> stays in history, not trusted
    to_reject = next(
        c for c in pending if c["candidate_id"] != entity_candidate["candidate_id"]
    )
    rejected = client.post(
        f"/candidates/{to_reject['candidate_id']}/reject",
        json={"reviewed_by": "acceptance-test", "reason": "not supported"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"

    # STEP 14: upload the same document again -> duplicate detected
    duplicate = upload_bytes(client, "acceptance_copy.txt", make_txt_bytes(TEXT))
    assert duplicate.status_code == 201
    dup_body = duplicate.json()
    assert dup_body["duplicate_of"] is not None
    assert dup_body["document"]["processing_status"] == "DUPLICATE"

    # STEP 15: search the trusted database
    search = client.get("/search?q=Arjun").json()
    assert any(e["canonical_name"] == "Arjun Mehta" for e in search["entities"])
    search_docs = client.get("/search?q=acceptance").json()
    assert any(d["filename"] == "acceptance.txt" for d in search_docs["documents"])

    # Audit trail exists
    audit = client.get("/audit").json()["items"]
    actions = {a["action"] for a in audit}
    assert "CONFIRM" in actions
    assert "REJECT" in actions
