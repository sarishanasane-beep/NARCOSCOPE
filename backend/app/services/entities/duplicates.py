"""Duplicate detection and safe canonicalization.

The investigation workstation never silently merges identity. Records are
classified into three states:

  - CONFIRMED SAME  — only for very high-confidence deterministic matches
                      (exact stable identity, e.g. same ENTITY_ID, or an
                      explicit human-approved merge).
  - POSSIBLE DUPLICATE — type-aware normalized-name matches flagged for
                      human review (default).
  - CONFIRMED DISTINCT — an explicit KEEP_SEPARATE decision suppresses
                      repeated flagging of the pair.

Merge is an explicit, audited operation that REPOINTS every reference
(relationships, facts, events, documents) to the canonical record and
marks the duplicate MERGED — provenance is preserved, nothing is deleted.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.duplicate_decision import DECISION_KEEP_SEPARATE, DuplicateDecision
from app.models.entity import (
    ENTITY_STATUS_ACTIVE,
    ENTITY_STATUS_MERGED,
    ENTITY_TYPE_CASE,
    Entity,
)
from app.models.event import Event
from app.models.fact import Fact
from app.models.location import Location
from app.models.relationship import Relationship
from app.services.audit.service import log_action
from app.utils.errors import NotFoundError, ValidationError
from app.utils.text import normalize_case_number, normalize_name


# ---------------------------------------------------------------------------
# Normalization keys
# ---------------------------------------------------------------------------


def entity_key(entity_type: str, name: str) -> str:
    """Type-aware comparison key: ``TYPE|normalized-name``.

    ``PERSON + Mumbai`` and ``LOCATION + Mumbai`` are deliberately
    different keys — type-aware deduplication never merges across types.
    """
    return f"{entity_type.strip().upper()}|{normalize_name(name)}"


def case_key(case: Case) -> str:
    """Comparison key for a Case (official number preferred)."""
    if case.official_case_number:
        return f"number|{normalize_case_number(case.official_case_number)}"
    if case.case_name:
        return f"name|{normalize_name(case.case_name)}"
    return f"id|{case.case_id}"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _known_decisions(db: Session, kind: str) -> set[tuple[str, str]]:
    """Canonicalized (record_a, record_b) pairs with a stored decision."""
    pairs: set[tuple[str, str]] = set()
    for decision in db.query(DuplicateDecision).filter(DuplicateDecision.kind == kind).all():
        pairs.add(tuple(sorted((decision.record_a_id, decision.record_b_id))))
    return pairs


def detect_entity_duplicates(db: Session) -> list[dict[str, Any]]:
    """Type-aware possible-duplicate entity groups.

    Groups ACTIVE, non-merged entities by ``TYPE|normalized-name``. Exact
    stable identity (same structured ENTITY_ID) is treated as CONFIRMED
    SAME; everything else is POSSIBLE DUPLICATE for human review. Pairs
    with an explicit KEEP_SEPARATE decision are not re-flagged.
    """
    kept_decisions = _known_decisions(db, "entity")
    by_key: dict[str, list[Entity]] = defaultdict(list)
    for entity in (
        db.query(Entity)
        .filter(Entity.status == ENTITY_STATUS_ACTIVE, Entity.merged_into_id.is_(None))
        .all()
    ):
        by_key[entity_key(entity.entity_type, entity.canonical_name)].append(entity)

    groups: list[dict[str, Any]] = []
    for key, records in sorted(by_key.items()):
        if len(records) < 2:
            continue
        entity_type = key.split("|")[0]
        # Exact structured ENTITY_ID match -> CONFIRMED SAME (deterministic).
        ids = [r.structured_metadata.get("entity_id") for r in records if r.structured_metadata]
        confirmed = len(ids) > 1 and len(set(ids)) == 1
        # Pairs explicitly kept separate are never re-flagged.
        pairs = [tuple(sorted((a.entity_id, b.entity_id))) for a in records for b in records if a.entity_id < b.entity_id]
        if pairs and all(p in kept_decisions for p in pairs):
            continue
        groups.append({
            "kind": "entity",
            "entity_type": entity_type,
            "canonical_name": records[0].canonical_name,
            "similarity": 1.0,
            "classification": "CONFIRMED_SAME" if confirmed else "POSSIBLE_DUPLICATE",
            "records": [
                {
                    "record_id": r.entity_id,
                    "record_type": "entity",
                    "name": r.canonical_name,
                    "entity_type": r.entity_type,
                    "source_document_id": r.document_id,
                    "structured_id": (r.structured_metadata or {}).get("entity_id"),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in sorted(records, key=lambda x: x.created_at)
            ],
        })
    return groups


def detect_case_duplicates(db: Session) -> list[dict[str, Any]]:
    """Possible-duplicate Case groups by normalized number/name."""
    kept_decisions = _known_decisions(db, "case")
    by_key: dict[str, list[Case]] = defaultdict(list)
    for case in db.query(Case).filter(Case.merged_into_id.is_(None)).all():
        by_key[case_key(case)].append(case)

    groups: list[dict[str, Any]] = []
    for key, records in sorted(by_key.items()):
        if len(records) < 2:
            continue
        pairs = [tuple(sorted((a.case_id, b.case_id))) for a in records for b in records if a.case_id < b.case_id]
        if pairs and all(p in kept_decisions for p in pairs):
            continue
        groups.append({
            "kind": "case",
            "canonical_name": records[0].case_name or records[0].official_case_number or "(case)",
            "similarity": 1.0,
            "classification": "POSSIBLE_DUPLICATE",
            "records": [
                {
                    "record_id": c.case_id,
                    "record_type": "case",
                    "name": c.case_name or c.official_case_number or "(case)",
                    "official_case_number": c.official_case_number,
                    "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in sorted(records, key=lambda x: x.created_at)
            ],
        })
    return groups


def _case_comparison_keys(case: Case) -> set[str]:
    """Normalized comparison keys for one Case (name + number)."""
    keys: set[str] = set()
    for value in (case.case_name, case.operation_name, case.official_case_number):
        if value:
            keys.add(normalize_name(value))
    return keys


def detect_case_entity_duplicates(db: Session) -> list[dict[str, Any]]:
    """CASE-typed entities that mirror an actual Case record.

    A legacy CASE-typed Entity (``Operation WHITE STRIKE [CASE]``) and the
    real Case record (``Operation WHITE STRIKE``) represent the same
    logical Case. They are matched ONLY by type (CASE) + normalized name —
    never by name alone — and flagged for human reconciliation.

    Classification:
      - CONFIRMED SAME when the entity's source document is anchored to
        that Case (Document.case_id) — a deterministic identity signal.
      - POSSIBLE DUPLICATE otherwise (review required, never auto-merged).
    """
    kept_decisions = _known_decisions(db, "case_entity")
    groups: list[dict[str, Any]] = []
    active_entities = [
        e for e in db.query(Entity).filter(Entity.status == ENTITY_STATUS_ACTIVE).all()
        if e.entity_type == ENTITY_TYPE_CASE
    ]
    for case in db.query(Case).filter(Case.merged_into_id.is_(None)).all():
        case_keys = _case_comparison_keys(case)
        if not case_keys:
            continue
        matches = [
            e for e in active_entities
            if normalize_name(e.canonical_name) in case_keys
        ]
        if not matches:
            continue
        if all(tuple(sorted((e.entity_id, case.case_id))) in kept_decisions for e in matches):
            continue
        from app.models.document import Document

        # Deterministic identity: the entity came from a document anchored
        # to this exact case record.
        doc_ids = {d.document_id for d in matches if d.document_id}
        anchored = (
            db.query(Document.document_id)
            .filter(Document.document_id.in_(doc_ids), Document.case_id == case.case_id)
            .count()
        ) if doc_ids else 0
        confirmed = anchored > 0
        groups.append({
            "kind": "case_entity",
            "canonical_name": case.case_name or case.official_case_number or "(case)",
            "similarity": 1.0,
            "classification": "CONFIRMED_SAME" if confirmed else "POSSIBLE_DUPLICATE",
            "case": {
                "record_id": case.case_id,
                "record_type": "case",
                "name": case.case_name or case.official_case_number or "(case)",
                "official_case_number": case.official_case_number,
                "status": case.status,
            },
            "records": [
                {
                    "record_id": e.entity_id,
                    "record_type": "entity",
                    "name": e.canonical_name,
                    "entity_type": e.entity_type,
                    "source_document_id": e.document_id,
                    "structured_id": (e.structured_metadata or {}).get("entity_id"),
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in sorted(matches, key=lambda x: x.created_at)
            ],
        })
    return groups


def detect_duplicates(db: Session, kind: str | None = None) -> list[dict[str, Any]]:
    """All possible-duplicate groups, or one kind.

    Kinds: ``entity`` | ``case`` | ``case_entity`` (CASE-typed entity that
    mirrors an actual Case). ``None`` returns everything.
    """
    groups: list[dict[str, Any]] = []
    if kind in (None, "entity"):
        groups += detect_entity_duplicates(db)
    if kind in (None, "case"):
        groups += detect_case_duplicates(db)
    if kind in (None, "case_entity"):
        groups += detect_case_entity_duplicates(db)
    return groups


def duplicate_summary(db: Session) -> dict[str, Any]:
    """Data-quality counts for Data Management (no hardcoded values)."""
    groups = detect_duplicates(db)
    entity_groups = [g for g in groups if g["kind"] == "entity"]
    case_groups = [g for g in groups if g["kind"] == "case"]
    case_entity_groups = [g for g in groups if g["kind"] == "case_entity"]
    total_records = (
        db.query(Entity).filter(Entity.status == ENTITY_STATUS_ACTIVE).count()
        + db.query(Case).count()
    )
    merged_records = (
        db.query(Entity).filter(Entity.status == ENTITY_STATUS_MERGED).count()
        + db.query(Case).filter(Case.merged_into_id.isnot(None)).count()
    )
    possible = [g for g in groups if g["classification"] == "POSSIBLE_DUPLICATE"]
    confirmed = [g for g in groups if g["classification"] == "CONFIRMED_SAME"]
    decisions = db.query(DuplicateDecision).count()
    return {
        "total_records": total_records,
        "possible_duplicate_groups": len(possible),
        "confirmed_same_groups": len(confirmed),
        "merged_records": merged_records,
        "keep_separate_decisions": decisions,
        "entity_duplicate_groups": len(entity_groups),
        "case_duplicate_groups": len(case_groups),
        "case_entity_reconciliation_groups": len(case_entity_groups),
    }


# ---------------------------------------------------------------------------
# Merge (explicit, audited, reference-preserving)
# ---------------------------------------------------------------------------


def _repoint(
    db: Session,
    model: type,
    field_name: str,
    from_id: str,
    to_id: str,
    kind_label: str,
    user: str | None,
) -> int:
    moved = 0
    for row in db.query(model).filter(getattr(model, field_name) == from_id).all():
        setattr(row, field_name, to_id)
        moved += 1
    if moved:
        log_action(
            db, action="MERGE", object_type=kind_label,
            object_id=to_id, new_value={f"{field_name}_from": from_id, f"{field_name}_to": to_id},
            reason=f"references repointed during merge ({moved} record(s))", user=user,
        )
    return moved


def merge_entities(
    db: Session,
    canonical_id: str,
    duplicate_id: str,
    *,
    user: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Merge ``duplicate`` into ``canonical`` (explicit human approval).

    Repoints every reference (relationships, facts, event locations,
    parent locations), marks the duplicate MERGED and preserves the
    canonical record's provenance. Nothing is deleted.
    """
    if canonical_id == duplicate_id:
        raise ValidationError("Canonical and duplicate must be different records.")
    canonical = db.get(Entity, canonical_id)
    duplicate = db.get(Entity, duplicate_id)
    if canonical is None or duplicate is None:
        raise NotFoundError("Entity not found.")
    if canonical.status != ENTITY_STATUS_ACTIVE or canonical.merged_into_id:
        raise ValidationError("Canonical entity is not active.")
    if duplicate.status == ENTITY_STATUS_MERGED:
        raise ValidationError("Duplicate entity is already merged.")

    # 1) Repoint graph references.
    _repoint(db, Relationship, "source_entity_id", duplicate_id, canonical_id, "relationship", user)
    _repoint(db, Relationship, "target_entity_id", duplicate_id, canonical_id, "relationship", user)
    _repoint(db, Fact, "subject_entity_id", duplicate_id, canonical_id, "fact", user)
    _repoint(db, Fact, "object_entity_id", duplicate_id, canonical_id, "fact", user)

    # 2) Location-specific references (events + parent locations). The
    #    duplicate's specialized Location row is preserved (no deletion) —
    #    only references are repointed to the canonical location.
    if duplicate.location is not None and canonical.location is not None:
        _repoint(
            db, Event, "location_id",
            duplicate.location.location_id, canonical.location.location_id, "event", user,
        )
        for loc in db.query(Location).filter(
            Location.parent_location_id == duplicate.location.location_id
        ).all():
            loc.parent_location_id = canonical.location.location_id

    # 3) Mark the duplicate merged (canonical stays ACTIVE).
    duplicate.status = ENTITY_STATUS_MERGED
    duplicate.merged_into_id = canonical_id
    db.flush()
    log_action(
        db, action="MERGE", object_type="entity", object_id=canonical_id,
        new_value={"duplicate_entity_id": duplicate_id, "canonical_name": canonical.canonical_name},
        reason=note or "duplicate entity merged into canonical record", user=user,
    )
    return {
        "canonical_id": canonical_id,
        "merged_id": duplicate_id,
        "status": "merged",
    }


def merge_cases(
    db: Session,
    canonical_id: str,
    duplicate_id: str,
    *,
    user: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Merge ``duplicate`` Case into ``canonical`` Case (explicit approval)."""
    if canonical_id == duplicate_id:
        raise ValidationError("Canonical and duplicate must be different records.")
    canonical = db.get(Case, canonical_id)
    duplicate = db.get(Case, duplicate_id)
    if canonical is None or duplicate is None:
        raise NotFoundError("Case not found.")
    if duplicate.merged_into_id:
        raise ValidationError("Duplicate case is already merged.")

    from app.models.document import Document
    from app.models.event import Event

    _repoint(db, Relationship, "case_id", duplicate_id, canonical_id, "relationship", user)
    _repoint(db, Event, "case_id", duplicate_id, canonical_id, "event", user)
    _repoint(db, Fact, "case_id", duplicate_id, canonical_id, "fact", user)
    for doc in db.query(Document).filter(Document.case_id == duplicate_id).all():
        doc.case_id = canonical_id
    duplicate.merged_into_id = canonical_id
    db.flush()
    log_action(
        db, action="MERGE", object_type="case", object_id=canonical_id,
        new_value={"duplicate_case_id": duplicate_id, "case_name": canonical.case_name},
        reason=note or "duplicate case merged into canonical record", user=user,
    )
    return {"canonical_id": canonical_id, "merged_id": duplicate_id, "status": "merged"}


def keep_separate(
    db: Session,
    kind: str,
    record_a_id: str,
    record_b_id: str,
    *,
    user: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record an explicit CONFIRMED DISTINCT decision for a pair.

    The pair is then excluded from future duplicate scans.
    """
    if kind not in ("entity", "case", "case_entity"):
        raise ValidationError("kind must be 'entity', 'case' or 'case_entity'.")
    db.add(
        DuplicateDecision(
            decision_id=str(uuid.uuid4()),
            kind=kind,
            record_a_id=record_a_id,
            record_b_id=record_b_id,
            decision=DECISION_KEEP_SEPARATE,
            decided_by=user,
            note=note,
        )
    )
    db.flush()
    log_action(
        db, action="UPDATE", object_type="duplicate_decision",
        object_id=f"{kind}:{record_a_id}:{record_b_id}",
        new_value={"decision": DECISION_KEEP_SEPARATE},
        reason=note or "records confirmed distinct — not flagged again", user=user,
    )
    return {"record_a_id": record_a_id, "record_b_id": record_b_id, "decision": DECISION_KEEP_SEPARATE}


def reconcile_case_entity(
    db: Session,
    entity_id: str,
    case_id: str,
    *,
    user: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Reconcile a CASE-typed Entity into the canonical Case record.

    The legacy CASE-entity (e.g. ``Operation WHITE STRIKE [CASE]``) is the
    same logical object as the real Case. Reconciliation is an explicit,
    audited human decision that:

      - marks the entity MERGED with ``merged_into_case_id`` (it never
        appears as an independent logical record again),
      - KEEPS the entity row as the relationship-endpoint FK target
        (nothing is deleted, no FK is broken),
      - preserves every relationship (already carries ``case_id``) and all
        provenance (evidence ids, documents, timestamps untouched).

    The graph service routes edges from reconciled CASE entities to the
    single canonical CASE node — no second logical Case is ever created.
    """
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("Entity not found.")
    case = db.get(Case, case_id)
    if case is None:
        raise NotFoundError("Case not found.")
    if entity.entity_type != ENTITY_TYPE_CASE:
        raise ValidationError("Only CASE-typed entities can be reconciled into a Case.")
    if entity.status != ENTITY_STATUS_ACTIVE and entity.merged_into_case_id != case_id:
        raise ValidationError("Entity is not active and is not reconciled to this case.")

    # Idempotent: reconciling the same pair twice is a no-op.
    if entity.status == ENTITY_STATUS_MERGED and entity.merged_into_case_id == case_id:
        return {"entity_id": entity_id, "case_id": case_id, "status": "reconciled", "already": True}

    meta = dict(entity.structured_metadata or {})
    meta["reconciled_into_case_id"] = case_id
    entity.structured_metadata = meta
    entity.status = ENTITY_STATUS_MERGED
    entity.merged_into_case_id = case_id
    db.flush()
    log_action(
        db, action="MERGE", object_type="case_entity", object_id=entity_id,
        new_value={"canonical_case_id": case_id, "canonical_name": case.case_name or case.official_case_number},
        reason=note or "CASE-typed entity reconciled into the canonical Case record", user=user,
    )
    return {"entity_id": entity_id, "case_id": case_id, "status": "reconciled", "already": False}
