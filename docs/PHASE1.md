# NARCOSCOPE — Phase 1 design notes

## Data model (SQLite is the source of truth)

```
Document 1───* Evidence *───1 Source
Document 1───* Candidate *───1 Evidence
Entity 1───1 Person / Organization / Location
Entity *───* Entity   (via Relationship, with type/classification/status)
Case 1───* Event
Case 1───* Fact / Relationship
Entity 1───* Fact   (subject; optional object entity/event/case)
Claim *───1 Evidence
Candidate *───1 Evidence
AuditLog (append-only, no FKs)
```

### Processing statuses
`UPLOADED · PROCESSING · PROCESSED · REVIEW_REQUIRED · FAILED · DUPLICATE`

### Candidate types
`ENTITY · RELATIONSHIP · CASE_MATCH · EVENT · LOCATION · FACT`

### Candidate statuses
`PENDING → (EDIT → EDITED) → CONFIRMED | REJECTED`

### Entity types
`PERSON · ORGANIZATION · AGENCY · LOCATION · PROPERTY · OTHER`

### Event types
`OPERATION · ARREST · SEIZURE · RAID · INVESTIGATION · SEARCH · COURT_PROCEEDING · INTERCEPTION · OTHER`

### Date precision
`DAY · MONTH · YEAR · RANGE · UNKNOWN`

### Relationship types
`MENTIONED_IN · INVOLVED_IN · ROLE_IN · QUESTIONED_IN · ARRESTED_IN · PARTICIPATED_IN · ASSOCIATED_WITH · OPERATES · OWNS · LOCATED_IN · RESIDES_IN · OCCURRED_IN · PART_OF · JURISDICTION`

### Classification / status
`DIRECT · DERIVED · CANDIDATE` and `CANDIDATE · CONFIRMED · REJECTED`

### Claim statuses
`REPORTED · ALLEGED · OFFICIALLY_STATED · COURT_RECORDED · UNKNOWN`

## Evidence chain
`ENTITY → RELATIONSHIP → EVIDENCE → SOURCE → ORIGINAL DOCUMENT`

Every candidate stores an `evidence_id`; evidence stores the exact source
text plus page and character offsets into the cleaned extracted text. The
original uploaded file is never modified and remains on disk.

## Deterministic extraction

- Sentence segmentation with abbreviation handling (`Mr.`, `S.`, …).
- Dates: day/month/year regexes, numeric `DD/MM/YYYY`, ranges, month-only,
  year-only; no fabrication.
- Case numbers: `Case No. …`, `FIR No. …`, `NCB/MUM/123/2026`, `CASE-001`.
- Entities: controlled location/organization dictionaries, operation-name
  pattern, acronyms, title prefixes, verb-context rules; initial forms
  (`S. Kulkarni`) become aliases within the same sentence.
- Events: keyword mapping with operation-aware titles and attached
  date/location/case when supported.
- Relationships: conservative verb patterns only (arrested during, took
  place in, resides in, located in, operates in, was seen with, led,
  participated in). Endpoints are cross-checked against detected entities.
- Facts: case-targeted patterns (involved in, questioned in connection
  with, mentioned/named in).
- Claims: alleged / reportedly / officially stated / court recorded.

## Review workflow

`confirm_candidate` validates the candidate, materializes the trusted
record (entity + specialized row, event, relationship, fact, or case),
preserves evidence, writes audit entries and marks the candidate
`CONFIRMED`. `reject_candidate` keeps the record in history only.
`update_candidate` moves `PENDING → EDITED`.

Entity confirmation never auto-merges: identical names create a new record
and a possible-match audit note is written (RULE 9).

## Matching

Weighted score — name 40 %, alias/context 25 %, location 15 %,
org/context 20 % — plus a +25 exact-name bonus. Thresholds:
`0–59 KEEP_SEPARATE`, `60–84 POSSIBLE_MATCH`, `85–100 STRONG_MATCH`.
Human confirmation is required before any merge; there is no auto-merge
path in Phase 1.

Case matching: exact official number → link; name-only → `POSSIBLE_MATCH`
(link after confirmation); otherwise create a new case candidate.
