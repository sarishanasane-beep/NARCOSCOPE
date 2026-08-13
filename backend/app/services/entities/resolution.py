"""Entity resolution.

Creates trusted entity records (Entities + specialized tables) when a
candidate is confirmed. Exact-name matches to existing entities are NEVER
silently merged: a new record is created and a possible-match note is
logged (RULE 9: similar names do not automatically mean same person).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.entity import (
    ENTITY_STATUS_ACTIVE,
    ENTITY_TYPE_LOCATION,
    ENTITY_TYPE_ORGANIZATION,
    ENTITY_TYPE_PERSON,
    Entity,
)
from app.models.location import Location
from app.models.organization import Organization
from app.models.person import Person
from app.services.audit.service import log_action
from app.services.entities.matching import MATCH_POSSIBLE, MATCH_STRONG, score_match
from app.utils.text import normalize_name

import logging

logger = logging.getLogger(__name__)


def find_entity_by_name(
    db: Session, name: str, entity_type: str | None = None
) -> Entity | None:
    """Exact normalized-name lookup among ACTIVE entities."""
    normalized = normalize_name(name)
    query = db.query(Entity).filter(Entity.status == ENTITY_STATUS_ACTIVE)
    if entity_type:
        query = query.filter(Entity.entity_type == entity_type)
    for entity in query.all():
        if normalize_name(entity.canonical_name) == normalized:
            return entity
    return None


def create_entity(
    db: Session,
    *,
    entity_type: str,
    canonical_name: str,
    aliases: list[str] | None = None,
    notes: str | None = None,
    parent_location: str | None = None,
    location_type: str = "OTHER",
    organization_type: str = "ORGANIZATION",
    structured_metadata: dict | None = None,
    document_id: str | None = None,
    user: str | None = None,
) -> Entity:
    """Create a trusted entity plus its specialized record.

    Possible matches against existing entities are logged (never
    auto-merged) so the human reviewer can decide. ``structured_metadata``
    carries structured-source semantics (role, status, mention_context,
    investigative_status) so the distinction between a contextual mention
    and an investigative subject survives confirmation. ``document_id``
    records the source document so case scoping of isolated entities is
    possible without fabricating membership edges.
    """
    entity = Entity(
        entity_id=str(uuid.uuid4()),
        entity_type=entity_type,
        canonical_name=canonical_name,
        status=ENTITY_STATUS_ACTIVE,
        structured_metadata=structured_metadata,
        document_id=document_id,
    )
    db.add(entity)
    db.flush()

    if entity_type == ENTITY_TYPE_PERSON:
        db.add(
            Person(
                person_id=str(uuid.uuid4()),
                entity_id=entity.entity_id,
                canonical_name=canonical_name,
                aliases=aliases or [],
                notes=notes,
            )
        )
    elif entity_type == ENTITY_TYPE_ORGANIZATION:
        db.add(
            Organization(
                organization_id=str(uuid.uuid4()),
                entity_id=entity.entity_id,
                canonical_name=canonical_name,
                aliases=aliases or [],
                organization_type=organization_type,
                notes=notes,
            )
        )
    elif entity_type == ENTITY_TYPE_LOCATION:
        parent_id = None
        if parent_location and normalize_name(parent_location) != normalize_name(canonical_name):
            parent = find_entity_by_name(db, parent_location, ENTITY_TYPE_LOCATION)
            if parent is not None and parent.location is not None:
                parent_id = parent.location.location_id
            else:
                parent_entity = create_entity(
                    db,
                    entity_type=ENTITY_TYPE_LOCATION,
                    canonical_name=parent_location,
                    location_type="OTHER",
                    notes="Created as parent location during confirmation.",
                    user=user,
                )
                parent_id = parent_entity.location.location_id
        db.add(
            Location(
                location_id=str(uuid.uuid4()),
                entity_id=entity.entity_id,
                canonical_name=canonical_name,
                location_type=location_type,
                parent_location_id=parent_id,
            )
        )
    db.flush()

    log_action(
        db,
        action="CREATE",
        object_type="entity",
        object_id=entity.entity_id,
        new_value={
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "aliases": aliases or [],
        },
        reason="candidate confirmation",
        user=user,
    )

    # Never auto-merge: note possible matches for the human reviewer.
    matches = score_match(
        db,
        name=canonical_name,
        entity_type=entity_type,
        aliases=aliases,
        location=parent_location,
        context=notes,
        exclude_entity_id=entity.entity_id,
    )
    for match in matches:
        if match.verdict in (MATCH_POSSIBLE, MATCH_STRONG):
            logger.info(
                "possible_entity_match candidate=%s existing=%s score=%s verdict=%s",
                canonical_name,
                match.name,
                match.score,
                match.verdict,
            )
            log_action(
                db,
                action="UPDATE",
                object_type="entity",
                object_id=entity.entity_id,
                new_value={"possible_match": match.entity_id, "score": match.score, "verdict": match.verdict},
                reason="Possible entity match noted; NO automatic merge performed.",
                user=user,
            )
    return entity
