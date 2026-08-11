"""Seed the NARCOSCOPE demo dataset.

Usage (from the backend directory):

    python scripts/seed_demo.py

All demo data is synthetic and clearly labeled DEMO DATA.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.init_db import init_db  # noqa: E402
from app.services.demo.seed import seed_demo  # noqa: E402

if __name__ == "__main__":
    init_db()
    summary = seed_demo()
    print("=== NARCOSCOPE DEMO DATA SEEDED ===")
    print(f"  documents uploaded:   {summary.documents}")
    print(f"  duplicates detected:  {summary.duplicates}")
    print(f"  people:               {summary.people}")
    print(f"  organizations:        {summary.organizations}")
    print(f"  locations:            {summary.locations}")
    print(f"  events:               {summary.events}")
    print(f"  cases:                {summary.cases}")
    print(f"  relationships:        {summary.relationships}")
    print(f"  facts:                {summary.facts}")
    print(f"  claims:               {summary.claims}")
    print(f"  candidates pending:   {summary.pending_candidates}")
