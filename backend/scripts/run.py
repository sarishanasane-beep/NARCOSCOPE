"""Start the NARCOSCOPE backend.

Usage (from the backend directory):

    python scripts/run.py

or:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
