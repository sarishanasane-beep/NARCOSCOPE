import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.entity import Entity
from app.models.location import Location
from app.models.organization import Organization
from app.models.person import Person
from app.schemas.entities import (
    EntityDetail,
    EntityList,
    EntityOut,
    LocationCreate,
    LocationList,
    LocationOut,
    OrganizationCreate,
    OrganizationList,
    OrganizationOut,
    PersonCreate,
    PersonList,
    PersonOut,
)
from app.services.audit.service import log_action
from app.services.entities.resolution import create_entity
from app.services.graph.cross_case import cross_case_connections
from app.services.search.history import entity_history
from app.services.search.timeline import entity_timeline
from app.utils.errors import NotFoundError, ValidationError

router = APIRouter(tags=["entities"])


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

@router.get("/entities", response_model=EntityList)
def list_entities(
    entity_type: str | None = None, limit: int = 200, offset: int = 0, db: Session = Depends(get_db)
) -> EntityList:
    query = db.query(Entity).order_by(Entity.canonical_name)
    if entity_type:
        query = query.filter(Entity.entity_type == entity_type)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return EntityList(items=[EntityOut.model_validate(e) for e in items], total=total)


@router.get("/entities/{entity_id}", response_model=EntityDetail)
def get_entity(entity_id: str, db: Session = Depends(get_db)) -> EntityDetail:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError("Entity not found.")
    detail = EntityDetail.model_validate(entity)
    if entity.person:
        detail.person = PersonOut.model_validate(entity.person)
    if entity.organization:
        detail.organization = OrganizationOut.model_validate(entity.organization)
    if entity.location:
        detail.location = LocationOut.model_validate(entity.location)
    return detail


# ---------------------------------------------------------------------------
# Investigation views (Prompt 2 Part 2)
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_id}/history")
def get_entity_history(entity_id: str, db: Session = Depends(get_db)) -> dict:
    """DOCUMENTED INVESTIGATION HISTORY — neutral, evidence-based, spans
    ALL trusted cases. Never called "Criminal History"."""
    return entity_history(db, entity_id)


@router.get("/entities/{entity_id}/timeline")
def get_entity_timeline(entity_id: str, db: Session = Depends(get_db)) -> dict:
    """Chronological history timeline for one entity (event dates kept
    separate from source publication dates; precision preserved)."""
    items = entity_timeline(db, entity_id)
    return {"entity_id": entity_id, "total": len(items), "items": items}


@router.get("/entities/{entity_id}/cross-case")
def get_entity_cross_case(entity_id: str, db: Session = Depends(get_db)) -> dict:
    """Cross-case connections: one canonical entity across all trusted
    cases (never one node per case)."""
    return cross_case_connections(db, entity_id)


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

@router.get("/people", response_model=PersonList)
def list_people(limit: int = 200, offset: int = 0, db: Session = Depends(get_db)) -> PersonList:
    query = db.query(Person).order_by(Person.canonical_name)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return PersonList(items=[PersonOut.model_validate(p) for p in items], total=total)


@router.post("/people", response_model=PersonOut, status_code=201)
def create_person(payload: PersonCreate, db: Session = Depends(get_db)) -> PersonOut:
    entity = create_entity(
        db,
        entity_type="PERSON",
        canonical_name=payload.canonical_name,
        aliases=payload.aliases,
        notes=payload.notes,
    )
    db.commit()
    return PersonOut.model_validate(entity.person)


@router.get("/people/{person_id}", response_model=PersonOut)
def get_person(person_id: str, db: Session = Depends(get_db)) -> PersonOut:
    person = db.get(Person, person_id)
    if person is None:
        raise NotFoundError("Person not found.")
    return PersonOut.model_validate(person)


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

@router.get("/organizations", response_model=OrganizationList)
def list_organizations(
    limit: int = 200, offset: int = 0, db: Session = Depends(get_db)
) -> OrganizationList:
    query = db.query(Organization).order_by(Organization.canonical_name)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return OrganizationList(items=[OrganizationOut.model_validate(o) for o in items], total=total)


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(
    payload: OrganizationCreate, db: Session = Depends(get_db)
) -> OrganizationOut:
    entity = create_entity(
        db,
        entity_type="ORGANIZATION",
        canonical_name=payload.canonical_name,
        aliases=payload.aliases,
        organization_type=payload.organization_type,
        notes=payload.notes,
    )
    db.commit()
    return OrganizationOut.model_validate(entity.organization)


@router.get("/organizations/{organization_id}", response_model=OrganizationOut)
def get_organization(organization_id: str, db: Session = Depends(get_db)) -> OrganizationOut:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")
    return OrganizationOut.model_validate(organization)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@router.get("/locations", response_model=LocationList)
def list_locations(limit: int = 200, offset: int = 0, db: Session = Depends(get_db)) -> LocationList:
    query = db.query(Location).order_by(Location.canonical_name)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return LocationList(items=[LocationOut.model_validate(l) for l in items], total=total)


@router.post("/locations", response_model=LocationOut, status_code=201)
def create_location(payload: LocationCreate, db: Session = Depends(get_db)) -> LocationOut:
    entity = create_entity(
        db,
        entity_type="LOCATION",
        canonical_name=payload.canonical_name,
        location_type=payload.location_type,
    )
    location = entity.location
    if payload.parent_location_id:
        parent = db.get(Location, payload.parent_location_id)
        if parent is None:
            raise NotFoundError("Parent location not found.")
        location.parent_location_id = parent.location_id
    if payload.latitude is not None:
        location.latitude = payload.latitude
    if payload.longitude is not None:
        location.longitude = payload.longitude
    db.commit()
    return LocationOut.model_validate(location)


@router.get("/locations/{location_id}", response_model=LocationOut)
def get_location(location_id: str, db: Session = Depends(get_db)) -> LocationOut:
    location = db.get(Location, location_id)
    if location is None:
        raise NotFoundError("Location not found.")
    return LocationOut.model_validate(location)
