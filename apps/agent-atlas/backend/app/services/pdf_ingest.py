"""
pdf_ingest.py  --  PDF -> Markdown, for the obsidian indexer to pick up
PDFs sitting in the vault alongside notes.

Deliberately a small local copy of shared/lib/pdf.py's logic rather than
an import across venvs: Agent Atlas has its own requirements.txt and its
own .venv (it's meant to run as an independent service, not coupled to
the rest of the monorepo's Python environment), so it depends on
pymupdf4llm directly instead of reaching into shared/lib.
"""

from pathlib import Path
from typing import Optional


def extract_pdf_markdown(path: str | Path) -> Optional[str]:
    """Convert a PDF to Markdown text, or None if it can't be read."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        import pymupdf4llm  # lazy import: optional dependency
    except Exception:  # noqa: BLE001
        return None
    try:
        md = pymupdf4llm.to_markdown(str(p))
    except Exception:  # noqa: BLE001
        return None
    return md if md.strip() else None
