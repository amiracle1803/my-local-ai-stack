"""
pdf.py  --  Turn a PDF file into clean Markdown text.

Engine: pymupdf4llm. Light, no torch/ML dependency, installs cleanly on
Windows, and produces Markdown good enough for an LLM to summarise or a
note to embed directly (headings, tables, and reading order preserved
better than a raw text dump).

There's no ML-heavy fallback (e.g. marker-pdf) wired in -- it pulls torch
for complex multi-column academic layouts, which hasn't come up. Add it
here the same way webfetch.py added crawl4ai if that ever becomes needed.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PdfResult:
    path: str
    text: str
    ok: bool
    pages: int = 0
    error: str = ""


def extract_pdf_markdown(path: str | Path) -> PdfResult:
    """Convert a PDF file to Markdown. Never raises -- check .ok."""
    p = Path(path)
    spath = str(p)
    if not p.exists():
        return PdfResult(spath, "", ok=False, error="file not found")

    try:
        import pymupdf4llm  # lazy import: optional dependency
    except Exception as exc:  # noqa: BLE001
        return PdfResult(spath, "", ok=False,
                         error=f"pymupdf4llm not installed: {exc}")

    try:
        md = pymupdf4llm.to_markdown(spath)
    except Exception as exc:  # noqa: BLE001
        return PdfResult(spath, "", ok=False, error=f"extraction failed: {exc}")

    ok = bool(md.strip())
    pages = md.count("\n-----\n") + 1 if ok else 0  # pymupdf4llm's page separator
    return PdfResult(spath, md, ok=ok, pages=pages,
                     error="" if ok else "no text extracted")
