"""Synthetic demo dataset — content definitions.

ALL DATA IS FICTIONAL (clearly labeled DEMO DATA). No real private
personal information is used. The dataset intentionally contains:

  1. one exact duplicate document
  2. two people with similar names
  3. one possible entity match
  4. one person appearing in multiple cases
  5. one organization appearing in multiple cases
  6. one event with exact date
  7. one event with month-only date
  8. one event with unknown date
  9. multiple evidence sources supporting one relationship
 10. one allegation
 11. one derived relationship
 12. one candidate relationship waiting for review
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER = "DEMO DATA — Synthetic document. All names and events are fictional."


@dataclass
class DemoDocument:
    key: str
    filename: str
    format: str  # txt | docx | pdf
    publisher: str
    agency: str
    source_type: str
    publication_date: str
    content: str


DEMO_DOCUMENTS: list[DemoDocument] = [
    DemoDocument(
        key="operation_bluewater",
        filename="demo_operation_bluewater.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-06-20",
        content=f"""{HEADER}

Operation Bluewater: Mumbai raid on 15 June 2026.

Officers of the Narcotics Control Bureau conducted a raid during Operation Bluewater in Mumbai on 15 June 2026. Inspector Suresh Patil led Operation Bluewater.

Arjun Mehta was arrested during Operation Bluewater. Vikram Jadhav was also arrested during Operation Bluewater. Rajesh Patil was also arrested during Operation Bluewater.

Authorities alleged that Vikram Jadhav supplied materials for the operation's target consignment.

Operation Bluewater took place in Mumbai. The raid took place in Mumbai, Maharashtra. A consignment of synthetic material was seized during the raid.

The case has been registered as Case CASE-001 with number NCB/MUM/123/2026.

The Narcotics Control Bureau operates in Mumbai. Mumbai Police also operates in Mumbai.
""",
    ),
    DemoDocument(
        key="operation_bluewater_second_report",
        filename="demo_operation_bluewater_second_report.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-06-22",
        content=f"""{HEADER}

Follow-up report on Operation Bluewater.

The Narcotics Control Bureau has confirmed that Arjun Mehta was arrested during Operation Bluewater on 15 June 2026.

The Directorate of Revenue Intelligence and the Customs Department also participated in Operation Bluewater.

Inspector Suresh Patil was questioned in connection with Case CASE-001.

Vikram Jadhav was questioned in connection with Case CASE-001.

The Directorate of Revenue Intelligence operates in Mumbai. The Customs Department operates in Mumbai. Mumbai Police participated in Operation Bluewater.
""",
    ),
    DemoDocument(
        key="operation_silverline",
        filename="demo_operation_silverline.docx",
        format="docx",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-07-05",
        content=f"""{HEADER}

Operation Silverline in Pune.

A seizure was carried out during Operation Silverline in Pune in June 2026.

Sameer Kulkarni was arrested during Operation Silverline. Nikhil Desai was also arrested during Operation Silverline.

Pune Police registered the case as Case CASE-002 with number FIR 456/2026.

Sameer Kulkarni is known to use the alias S. Kulkarni.

Pune Police operates in Pune. Nikhil Desai resides in Pune.
""",
    ),
    DemoDocument(
        key="interception_nashik",
        filename="demo_interception_nashik.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-07-10",
        content=f"""{HEADER}

Interception report from Nashik.

Communications linked to an investigation were intercepted by the Maharashtra Police in Nashik.

Rajesh Patil and Farhan Shaikh were questioned in connection with the matter.

The Maharashtra Police operates in Nashik. Narcotics Control Bureau operates in Nashik.

Communications routed through Goa and Delhi were also reviewed.

The date of the event is not recorded in the available records.

Farhan Shaikh resides in Nashik.
""",
    ),
    DemoDocument(
        key="court_proceeding",
        filename="demo_court_proceeding.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="COURT_PUBLIC_RECORD",
        publication_date="2026-07-06",
        content=f"""{HEADER}

Court proceeding notes for Case CASE-001.

The Bombay High Court held a hearing on 5 July 2026 in the matter of Arjun Mehta.

Advocate Meena Kulkarni appeared for Arjun Mehta. Judge Kavita Rao presided over the hearing.

Officially stated: the next hearing is scheduled for August 2026.

The court recorded that Kavita Rao will preside over the next hearing.

The hearing concerns Case CASE-001 in which Arjun Mehta is involved.

Meena Kulkarni resides in Mumbai.
""",
    ),
    DemoDocument(
        key="person_profile",
        filename="demo_person_profile.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-07-12",
        content=f"""{HEADER}

Profile notes for Sameer Kulkarni.

Sameer Kulkarni resides in Pune, Maharashtra.

Sameer Kulkarni is also referred to as S. Kulkarni in some records.

Sameer Kulkarni was involved in Case CASE-002.

Meera Kulkarni and Amit Deshmukh are documented in the same neighborhood records. Mahesh Gokhale also resides in Thane.

Meera Kulkarni resides in Pune. Amit Deshmukh resides in Thane.
""",
    ),
    DemoDocument(
        key="org_profile",
        filename="demo_org_profile.pdf",
        format="pdf",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-07-14",
        content=f"""{HEADER}

Organization profile: Blue Horizon Imports.

Blue Horizon Imports is located in Mumbai, Maharashtra.

Silverline Traders is also located in Mumbai.

Blue Horizon Imports was mentioned in Case CASE-001 and Case CASE-004.

Blue Horizon Imports operates in Mumbai.

A consignment destined for India was documented in the records.
""",
    ),
    DemoDocument(
        key="operation_redline",
        filename="demo_operation_redline.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-07-25",
        content=f"""{HEADER}

Operation Redline in Nashik.

Vikram Jadhav was arrested during Operation Redline on 22 July 2026.

Rahul Patel and Zubin Irani were also arrested during Operation Redline.

Farhan Shaikh was arrested during Operation Redline.

Maharashtra Police registered the case as Case CASE-003.

A search was conducted during Operation Redline.

Blue Horizon Imports operates in Nashik. Zubin Irani resides in Nashik.
""",
    ),
    DemoDocument(
        key="case_documents",
        filename="demo_case_documents.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="OFFICIAL_AGENCY",
        publication_date="2026-08-01",
        content=f"""{HEADER}

Case filing documents.

Arjun Mehta is named in Case CASE-004 and Case CASE-005.

Anil Kadam was involved in Case CASE-005.

Karan Shah and Varun Thakur were questioned in connection with Case CASE-005.

The FIR for Case CASE-005 is FIR 789/2026.

Varun Thakur resides in Pune.
""",
    ),
    DemoDocument(
        key="allegation_notes",
        filename="demo_allegation_notes.txt",
        format="txt",
        publisher="NARCOSCOPE Demo Unit",
        agency="Demo Data Team",
        source_type="SECONDARY_SOURCE",
        publication_date="2026-08-03",
        content=f"""{HEADER}

Investigative notes.

Reportedly, Karan Shah was seen with Nikhil Desai on two occasions in Mumbai.

Authorities alleged that Karan Shah coordinated with Silverline Traders.

Silverline Traders is located in Mumbai.

Rohit Mane and Deepak Naik were also mentioned in the notes. Prakash Bhandari also resides in Nashik.

Silverline Traders operates in Mumbai.
""",
    ),
]

# The exact duplicate: same content as the first document, different filename.
DUPLICATE_FILENAME = "demo_operation_bluewater_duplicate.txt"

# ---------------------------------------------------------------------------
# Allowlists used by the seed to confirm curated candidates
# (everything else stays PENDING for review).
# ---------------------------------------------------------------------------

PEOPLE_CONFIRM: set[str] = {
    "Arjun Mehta", "Vikram Jadhav", "Suresh Patil", "Rajesh Patil", "Sameer Kulkarni",
    "Nikhil Desai", "Farhan Shaikh", "Meena Kulkarni", "Kavita Rao", "Meera Kulkarni",
    "Amit Deshmukh", "Mahesh Gokhale", "Rahul Patel", "Zubin Irani", "Anil Kadam",
    "Karan Shah", "Varun Thakur", "Rohit Mane", "Deepak Naik", "Prakash Bhandari",
}

ORGANIZATIONS_CONFIRM: set[str] = {
    "Narcotics Control Bureau", "Directorate of Revenue Intelligence", "Customs Department",
    "Mumbai Police", "Pune Police", "Maharashtra Police", "Bombay High Court",
    "Blue Horizon Imports", "Silverline Traders",
}

LOCATIONS_CONFIRM: set[str] = {
    "Mumbai", "Pune", "Nashik", "Maharashtra", "Thane", "India", "Goa", "Delhi",
}

OPERATIONS_CONFIRM: set[str] = {
    "Operation Bluewater", "Operation Silverline", "Operation Redline",
}
