"""EXTRACTION TESTS."""

from pathlib import Path

from app.services.documents.extractors import (
    DOCXTextExtractor,
    PDFTextExtractor,
    TXTTextExtractor,
)
from app.services.extraction.dates import (
    DATE_PRECISION_DAY,
    DATE_PRECISION_MONTH,
    DATE_PRECISION_RANGE,
    DATE_PRECISION_YEAR,
    extract_dates,
)
from app.services.extraction.case_numbers import extract_case_numbers
from app.services.extraction.engine import run_extraction
from app.tests.conftest import (
    make_docx_bytes,
    make_pdf_bytes,
    make_txt_bytes,
)


def test_pdf_extraction(tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(make_pdf_bytes("Hello PDF world. Arjun Mehta was arrested."))
    pages = PDFTextExtractor().extract(path)
    assert pages
    text = " ".join(t for _, t in pages)
    assert "Arjun Mehta" in text
    assert "arrested" in text


def test_docx_extraction(tmp_path):
    path = tmp_path / "sample.docx"
    path.write_bytes(make_docx_bytes("Hello DOCX world.\nSameer Kulkarni resides in Pune."))
    pages = DOCXTextExtractor().extract(path)
    text = " ".join(t for _, t in pages)
    assert "Sameer Kulkarni" in text
    assert "Pune" in text


def test_txt_extraction(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_bytes(make_txt_bytes("Hello TXT world. Vikram Jadhav was arrested."))
    pages = TXTTextExtractor().extract(path)
    text = " ".join(t for _, t in pages)
    assert "Vikram Jadhav" in text


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

def test_date_day():
    dates = extract_dates("The raid happened on 15 June 2026.")
    assert len(dates) == 1
    assert dates[0].precision == DATE_PRECISION_DAY
    assert dates[0].normalized.isoformat() == "2026-06-15"


def test_date_month_only():
    dates = extract_dates("The seizure happened in June 2026.")
    assert dates[0].precision == DATE_PRECISION_MONTH
    assert dates[0].normalized.isoformat() == "2026-06-01"


def test_date_year_only():
    dates = extract_dates("Records for 2025 were reviewed.")
    assert dates[0].precision == DATE_PRECISION_YEAR
    assert dates[0].normalized.isoformat() == "2025-01-01"


def test_date_numeric():
    dates = extract_dates("Filed on 15/06/2026.")
    assert dates[0].precision == DATE_PRECISION_DAY
    assert dates[0].normalized.isoformat() == "2026-06-15"


def test_date_range():
    dates = extract_dates("Between 10 and 15 June 2026 the operation ran.")
    assert any(d.precision == DATE_PRECISION_RANGE for d in dates)
    values = {d.normalized.isoformat() for d in dates}
    assert "2026-06-10" in values
    assert "2026-06-15" in values


def test_no_fabricated_dates():
    dates = extract_dates("The date of the event is not recorded.")
    assert dates == []


# ---------------------------------------------------------------------------
# Case numbers
# ---------------------------------------------------------------------------

def test_case_number_agency_style():
    found = extract_case_numbers("Reference NCB/MUM/123/2026 was noted.")
    assert any(c.normalized == "NCB/MUM/123/2026" for c in found)


def test_case_number_fir():
    found = extract_case_numbers("FIR No. 123/2026 was registered.")
    assert any("123/2026" in c.normalized for c in found)


def test_case_number_case_no():
    found = extract_case_numbers("Case No. ABC/123/2026 assigned.")
    assert any("ABC/123/2026" in c.normalized for c in found)


def test_case_number_label_not_invented():
    # "Case No. CASE-TEST-001" must normalize to "CASE-TEST-001", not
    # "CASENO.CASE-TEST-001" — the label prefix is not part of the number.
    found = extract_case_numbers("Case No. CASE-TEST-001 was registered.")
    assert any(c.normalized == "CASE-TEST-001" for c in found)
    assert not any("CASENO" in c.normalized for c in found)


def test_case_number_fir_prefix_stripped():
    # "FIR No. 123/2026" -> "123/2026" (the label is not the number).
    found = extract_case_numbers("FIR No. 123/2026 was registered.")
    assert any(c.normalized == "123/2026" for c in found)


def test_case_number_bare_case_label():
    # "Case CASE-001" (no No./Number) keeps the clean number too.
    found = extract_case_numbers("was questioned in connection with Case CASE-001.")
    assert any(c.normalized == "CASE-001" for c in found)


# ---------------------------------------------------------------------------
# Entities / events / relationships / claims via the full engine
# ---------------------------------------------------------------------------

def test_entity_extraction():
    result = run_extraction(
        "Arjun Mehta was arrested during Operation Bluewater in Mumbai. "
        "The Narcotics Control Bureau operates in Pune."
    )
    names = {(e.entity_type, e.name) for e in result.entities}
    assert ("PERSON", "Arjun Mehta") in names
    assert ("OTHER", "Operation Bluewater") in names
    assert ("LOCATION", "Mumbai") in names
    assert ("LOCATION", "Pune") in names
    assert ("ORGANIZATION", "Narcotics Control Bureau") in names


def test_event_extraction():
    result = run_extraction(
        "Sameer Kulkarni was arrested during Operation Silverline on 22 July 2026."
    )
    events = {(e.event_type, e.title) for e in result.events}
    assert ("ARREST", "Arrest of Sameer Kulkarni during Operation Silverline") in events
    arrest = next(e for e in result.events if e.event_type == "ARREST")
    assert arrest.date is not None
    assert arrest.date.precision == DATE_PRECISION_DAY


def test_month_only_event():
    result = run_extraction("A seizure was carried out during Operation Silverline in June 2026.")
    seizure = next(e for e in result.events if e.event_type == "SEIZURE")
    assert seizure.date is not None
    assert seizure.date.precision == DATE_PRECISION_MONTH


def test_unknown_date_event():
    result = run_extraction("An interception occurred in Nashik. The date is not recorded.")
    assert any(e.event_type == "INTERCEPTION" and e.date is None for e in result.events)


def test_relationship_extraction():
    result = run_extraction(
        "Arjun Mehta was arrested during Operation Bluewater. "
        "Operation Bluewater took place in Mumbai. "
        "Sameer Kulkarni resides in Pune."
    )
    rels = {(r.source_name, r.relationship_type, r.target_name) for r in result.relationships}
    assert ("Arjun Mehta", "ARRESTED_IN", "Operation Bluewater") in rels
    assert ("Operation Bluewater", "OCCURRED_IN", "Mumbai") in rels
    assert ("Sameer Kulkarni", "RESIDES_IN", "Pune") in rels


def test_no_cooccurrence_relationship():
    # Co-occurrence alone must NOT create a relationship.
    result = run_extraction(
        "Arjun Mehta and Sameer Kulkarni are both mentioned in this document. "
        "Nikhil Desai also appears in this paragraph."
    )
    assert result.relationships == []


def test_multi_source_arrest():
    result = run_extraction(
        "Rahul Patel and Zubin Irani were also arrested during Operation Redline."
    )
    rels = {(r.source_name, r.target_name) for r in result.relationships}
    assert ("Rahul Patel", "Operation Redline") in rels
    assert ("Zubin Irani", "Operation Redline") in rels


def test_alias_merge():
    result = run_extraction(
        "Sameer Kulkarni is also referred to as S. Kulkarni in some records."
    )
    persons = [e for e in result.entities if e.entity_type == "PERSON"]
    assert len(persons) == 1
    assert "S. Kulkarni" in persons[0].aliases


def test_fact_extraction():
    result = run_extraction(
        "Inspector Suresh Patil was questioned in connection with Case CASE-001."
    )
    assert any(
        f.predicate == "QUESTIONED_IN" and f.case_ref == "Case CASE-001" for f in result.facts
    )


def test_claim_extraction():
    result = run_extraction(
        "Authorities alleged that Vikram Jadhav supplied materials."
    )
    assert any(c.claim_status == "ALLEGED" for c in result.claims)
