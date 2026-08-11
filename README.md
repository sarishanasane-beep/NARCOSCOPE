# NARCOSCOPE — Phase 1

**Evidence-backed investigation-support platform.**

NARCOSCOPE organizes publicly available documents related to narcotics
investigations into a structured, searchable knowledge base that will later
become a knowledge graph.

Phase 1 delivers the working foundation: upload PDF / DOCX / TXT documents,
extract structured candidates **without any AI**, review and confirm / edit /
reject them, and store validated information in a trusted SQLite database —
with full evidence traceability and an audit trail.

> **AI is optional. The application runs in deterministic mode when no API
> key is configured.**

> ⚠️ **All demo data is synthetic and clearly labeled `DEMO DATA`.**
> NARCOSCOPE does **not** determine guilt, create guilt scores, or label
> people as criminals. It never merges uncertain people or turns allegations
> into facts.

---

## 1. Core principles

NARCOSCOPE is an investigation-support and information-organization platform.
It is **not** a system that determines guilt. The system never:

- determines that a person is guilty or predicts criminality
- creates a "guilt score" or "criminality score"
- labels a person as a criminal merely because they appear in a document
- assumes two people are connected because they appear in the same document
- invents relationships, dates, locations, case numbers or roles
- automatically merges uncertain people, organizations or cases
- turns allegations into established facts
- allows unverified AI output into the trusted dataset

**Terminology:** *Documented Investigation History*, *Documented
Information*, *Investigation Priority*, *Network Cluster*, *Candidate
Relationship*, *Confirmed Relationship*, *Evidence*, *Source*, *Candidate
Entity*, *Confirmed Entity*.

**Architectural rules (Phase 1):**

1. SQLite is the source of truth.
2. NetworkX (later) is an analysis layer, not the primary database.
3. Original documents are never destroyed.
4. Evidence must remain traceable: `ENTITY → RELATIONSHIP → EVIDENCE → SOURCE → ORIGINAL DOCUMENT`.
5. Candidate information is separate from trusted information.
6. AI output enters the candidate layer — always.
7. *Unknown* is better than *guessed*.
8. Co-occurrence is not automatically a relationship.
9. Similar names do not automatically mean the same person.
10. Similar case names do not automatically mean the same case.
11. An allegation must remain an allegation.
12. The system never determines guilt.
13. The system works without AI.
14. The schema supports future graph construction.

---

## 2. Architecture

```
narcoscope/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, error handlers, startup
│   │   ├── config/              # pydantic-settings configuration
│   │   ├── database/            # SQLAlchemy engine, session, init
│   │   ├── models/              # ORM models (documents, entities, cases…)
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── api/routes/          # REST endpoints
│   │   ├── services/
│   │   │   ├── documents/       # upload, validation, storage, extractors
│   │   │   ├── extraction/      # deterministic extraction engine
│   │   │   ├── entities/        # resolution + matching foundation
│   │   │   ├── cases/           # case matching foundation
│   │   │   ├── candidates/      # candidate persistence
│   │   │   ├── evidence/        # evidence storage
│   │   │   ├── sources/         # source metadata
│   │   │   ├── validation/      # review workflow (confirm/edit/reject)
│   │   │   ├── search/          # basic search
│   │   │   ├── audit/           # audit log
│   │   │   ├── ai/              # AI provider abstraction (optional)
│   │   │   └── demo/            # synthetic demo dataset + seed
│   │   └── tests/               # pytest suite
│   ├── scripts/                 # run.py, seed_demo.py
│   └── requirements.txt
├── data/
│   ├── documents/original/      # uploaded originals (never modified)
│   ├── documents/extracted/     # cleaned extracted text (inspection)
│   └── demo/                    # demo file generation
├── database/                    # SQLite database file (created at runtime)
├── docs/                        # phase documentation
├── frontend/                    # minimal review interface (index.html)
├── .env.example
└── README.md
```

**Extraction pipeline (deterministic, no AI):**

```
DOCUMENT → TEXT EXTRACTION → TEXT CLEANING → SENTENCE SEGMENTATION
→ DATE DETECTION → CASE NUMBER DETECTION → LOCATION / PERSON / ORGANIZATION
DETECTION → EVENT DETECTION → RELATIONSHIP PATTERN DETECTION
→ CANDIDATE CREATION
```

**Review workflow:**

```
EXTRACT → CANDIDATE → REVIEW (CONFIRM / EDIT / REJECT) → TRUSTED DATA
```

---

## 3. Supported input formats (V1 — locked)

| Format | Extension | Library |
|---|---|---|
| PDF | `.pdf` | PyMuPDF (fitz) |
| DOCX | `.docx` | python-docx |
| TXT | `.txt` | standard library (encoding-safe) |

Not implemented in V1: web scraping, online feeds, live government APIs,
CSV/JSON import, automatic URL crawling. The user manually uploads documents.

---

## 4. Installation

Requires **Python 3.10+**.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

---

## 5. Configuration

Copy `.env.example` to `.env` at the project root and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `AI_ENABLED` | `false` | AI is optional |
| `AI_PROVIDER` | *(empty)* | `gemini` / `openai` (not implemented in Phase 1) |
| `AI_API_KEY` | *(empty)* | never required to run |
| `DATABASE_URL` | `sqlite:///./database/narcoscope.db` | SQLite is the source of truth |
| `UPLOAD_DIRECTORY` | `./data/documents` | original + extracted files |
| `MAX_UPLOAD_SIZE` | `26214400` (25 MiB) | upload size limit (bytes) |
| `PROCESS_ON_UPLOAD` | `true` | extract + create candidates on upload |
| `LOG_LEVEL` | `INFO` | application log level |
| `DEBUG` | `false` | debug mode |

Secrets are never hard-coded and never exposed to the frontend. The app
**must** start with `AI_ENABLED=false` and an empty `AI_API_KEY` — and it does.

---

## 6. Run the backend

From the `backend/` directory:

```bash
python scripts/run.py
# or
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Review interface (minimal upload + review UI): http://127.0.0.1:8000/
- Interactive docs (Swagger): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

```json
{
  "status": "ok",
  "database": "connected",
  "ai_enabled": false
}
```

---

## 7. Demo data

Seed the synthetic dataset (10 documents including one exact duplicate,
5 cases, ~20 people, 8 organizations, 8 locations, ~20 events,
40+ relationships, claims, and one derived relationship waiting for review):

```bash
python scripts/seed_demo.py
```

All demo documents are generated as real TXT/DOCX/PDF files and run through
the **real** upload → extraction → candidate pipeline. A curated subset is
then confirmed so the trusted database contains a consistent demo graph.
Everything is labeled `DEMO DATA`.

---

## 8. Run the tests

```bash
cd backend
pytest
```

Coverage includes: file uploads (PDF/DOCX/TXT, invalid extension, oversized,
duplicate), extraction (PDF/DOCX/TXT, dates, case numbers, entities, events,
relationships, claims), database creation, the validation workflow
(create/confirm/reject/edit), entity matching (strong / possible / same
surname / same full name), case matching, claims, and a full end-to-end
acceptance test. **All tests run with `AI_ENABLED=false`.**

---

## 9. API overview

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/documents/upload` | Upload PDF/DOCX/TXT (+ optional metadata) |
| GET | `/documents` | List documents |
| GET | `/documents/{id}` | Document detail |
| POST | `/documents/{id}/process` | (Re)process a failed/uploaded document |
| GET | `/documents/{id}/similar` | Near-duplicate foundation |
| GET | `/sources`, `/sources/{id}` | Sources |
| GET | `/evidence/{id}` | Evidence (exact supporting text) |
| GET/POST | `/cases`, `/cases/{id}`, PUT `/cases/{id}` | Cases |
| GET | `/entities`, `/entities/{id}` | Entities |
| GET/POST | `/people`, `/people/{id}` | People |
| GET/POST | `/organizations`, `/organizations/{id}` | Organizations |
| GET/POST | `/locations`, `/locations/{id}` | Locations |
| GET/POST | `/events`, `/events/{id}` | Events |
| GET/POST | `/relationships`, `/relationships/{id}` | Relationships |
| GET | `/facts` | Facts |
| GET | `/claims` | Claims |
| GET | `/candidates`, `/candidates/{id}` | Candidates for review |
| POST | `/candidates/{id}/confirm` | Confirm → trusted data |
| POST | `/candidates/{id}/reject` | Reject (kept in history) |
| PUT | `/candidates/{id}` | Edit candidate (→ EDITED) |
| GET | `/audit` | Audit trail |
| GET | `/search?q=` | Basic search across trusted data |
| GET | `/health` | Health check |

All endpoints use Pydantic schemas for request/response validation.

---

## 10. AI configuration

AI is **optional**. The `AIProvider` abstraction defines the interface;
Phase 1 ships the `NoneProvider` (deterministic mode). When `AI_ENABLED`
is false — or a provider is configured but unimplemented — the service
falls back to deterministic mode and logs the fact.

AI may eventually be used for difficult entity/relationship extraction,
ambiguous resolution and summarizing already verified information. AI
output **always** enters the candidate layer. AI never determines guilt,
never auto-confirms or auto-merges, never modifies the trusted graph
directly, and never browses the internet.

---

## 11. Key design decisions

- **Candidates vs trusted data.** Extraction produces `Candidate` rows with
  `proposed_data`, confidence, reason and evidence. Nothing enters trusted
  tables (`entities`, `cases`, `events`, `relationships`, `facts`) until a
  human confirms it.
- **Evidence.** Every candidate references evidence (`exact_text`, page,
  offsets) which references a document and source. Original files are
  preserved on disk for verification.
- **Dates.** Never invented. `date_precision` is `DAY`, `MONTH`, `YEAR`,
  `RANGE` or `UNKNOWN`. Event dates and source publication dates are stored
  separately.
- **Matching.** Weighted similarity (name 40%, alias/context 25%, location
  15%, org/context 20%). `0–59` keep separate, `60–84` possible match
  (human review), `85–100` strong match (human confirmation still
  required). Identical names are `POSSIBLE_MATCH`, never auto-merged.
- **Claims.** "Authorities alleged that X…" is stored as a claim with
  `claim_status = ALLEGED` — never converted into a confirmed fact.
- **Duplicates.** SHA-256 hash. Exact duplicates are stored with
  `processing_status = DUPLICATE` and a reference to the original; they are
  never processed as independent evidence. A near-duplicate foundation
  (`/documents/{id}/similar`) uses extracted-text similarity.

---

## 12. Phase 1 acceptance workflow

1. Start the app (`python scripts/run.py`).
2. Confirm `AI_ENABLED=false`.
3. Upload a PDF (or TXT/DOCX) via the UI at `/` or `POST /documents/upload`.
4. The system stores the original, hashes it (SHA-256), extracts text.
5. The system detects people, organizations, locations, events, dates and
   case numbers, and creates candidate records with supporting evidence.
6. Review candidates (`GET /candidates` or the web UI): confirm one (it
   enters the trusted database), reject another (it stays in history only).
7. Upload the same document again → `"Duplicate document detected."`
8. Search the trusted database (`GET /search?q=…`) and run `pytest`.

---

## 13. Not in Phase 1

Deliberately deferred to later phases: final dashboard, advanced graph
visualization, NetworkX graph analytics (centrality, community detection,
shortest-path UI), graph snapshots / change detection, Investigation
Priority, advanced workspaces, and the polished final UI. The backend is
structured so these can be added cleanly later.
