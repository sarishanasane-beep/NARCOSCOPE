"""DATABASE TESTS — creating and reading trusted records."""

import uuid

from app.models.case import Case
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.location import Location
from app.models.organization import Organization
from app.models.person import Person
from app.models.relationship import Relationship
from app.services.entities.resolution import create_entity


def test_entity_and_person_creation(db):
    entity = create_entity(
        db,
        entity_type="PERSON",
        canonical_name="Arjun Mehta",
        aliases=["A. Mehta"],
        notes="DEMO DATA",
    )
    db.commit()
    assert entity.person is not None
    person = db.get(Person, entity.person.person_id)
    assert person is not None
    assert person.canonical_name == "Arjun Mehta"
    assert "A. Mehta" in person.aliases


def test_organization_creation(db):
    entity = create_entity(
        db,
        entity_type="ORGANIZATION",
        canonical_name="Narcotics Control Bureau",
        organization_type="AGENCY",
    )
    db.commit()
    org = db.get(Organization, entity.organization.organization_id)
    assert org is not None
    assert org.organization_type == "AGENCY"


def test_location_creation_with_parent(db):
    parent = create_entity(db, entity_type="LOCATION", canonical_name="Maharashtra")
    child = create_entity(
        db,
        entity_type="LOCATION",
        canonical_name="Pune",
        parent_location="Maharashtra",
    )
    db.commit()
    location = db.get(Location, child.location.location_id)
    assert location is not None
    assert location.parent_location_id == parent.location.location_id


def test_case_creation(db):
    case = Case(
        case_id=str(uuid.uuid4()),
        official_case_number="NCB/MUM/123/2026",
        case_name="CASE-001",
        jurisdiction="Maharashtra",
    )
    db.add(case)
    db.commit()
    assert db.get(Case, case.case_id).case_name == "CASE-001"


def test_event_creation(db):
    event = Event(
        event_id=str(uuid.uuid4()),
        event_type="OPERATION",
        title="Operation Bluewater",
        date_precision="DAY",
    )
    db.add(event)
    db.commit()
    assert db.get(Event, event.event_id).event_type == "OPERATION"


def test_evidence_creation(db):
    from app.models.document import Document

    document = Document(
        document_id=str(uuid.uuid4()),
        filename="a.txt",
        stored_filename="a.txt",
        file_type="txt",
        mime_type="text/plain",
        file_size=10,
        sha256_hash="0" * 64,
        storage_path="/tmp/a.txt",
        processing_status="UPLOADED",
    )
    db.add(document)
    db.flush()
    evidence = Evidence(
        evidence_id=str(uuid.uuid4()),
        document_id=document.document_id,
        exact_text="Arjun Mehta was arrested.",
        extraction_method="deterministic_rules",
    )
    db.add(evidence)
    db.commit()
    stored = db.get(Evidence, evidence.evidence_id)
    assert stored.exact_text == "Arjun Mehta was arrested."


def test_relationship_creation(db):
    person = create_entity(db, entity_type="PERSON", canonical_name="Arjun Mehta")
    operation = create_entity(db, entity_type="OTHER", canonical_name="Operation Bluewater")
    relationship = Relationship(
        relationship_id=str(uuid.uuid4()),
        source_entity_id=person.entity_id,
        relationship_type="ARRESTED_IN",
        target_entity_id=operation.entity_id,
        status="CONFIRMED",
    )
    db.add(relationship)
    db.commit()
    stored = db.get(Relationship, relationship.relationship_id)
    assert stored.relationship_type == "ARRESTED_IN"
    assert stored.source_entity_id == person.entity_id


def test_fact_creation(db):
    from app.models.fact import Fact

    person = create_entity(db, entity_type="PERSON", canonical_name="Suresh Patil")
    case = Case(case_id=str(uuid.uuid4()), case_name="CASE-001")
    db.add(case)
    db.flush()
    fact = Fact(
        fact_id=str(uuid.uuid4()),
        subject_entity_id=person.entity_id,
        predicate="QUESTIONED_IN",
        case_id=case.case_id,
        status="CONFIRMED",
    )
    db.add(fact)
    db.commit()
    assert db.get(Fact, fact.fact_id).predicate == "QUESTIONED_IN"
