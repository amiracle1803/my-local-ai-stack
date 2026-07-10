"""Deterministic character chunking (design 5.1 / original spec Stage 1 Step 1,
reused wherever "chunked like Step 1" is specified -- including Stage 0's
brief/world-bible context assembly).

Backed by ``chonkie``'s ``TokenChunker`` with the character tokenizer, which
makes "tokens" == characters, so ``chunk_size``/``chunk_overlap`` are exactly
character counts (the original spec's numbers: 8000 / 400). Offsets returned
by chonkie are exact slice positions into the source text (the character
tokenizer round-trips losslessly), so reassembly is a straightforward
overlap-trim -- see :func:`reassemble_chunks`, used by tests to prove
zero-loss chunking.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from chonkie import TokenChunker
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "chonkie is required for pipeline.chunking (see requirements.txt: "
        "'chonkie>=0.4'). Install it in the stack venv with "
        "`.venv\\Scripts\\python.exe -m pip install chonkie`."
    ) from exc

# Original spec numbers (Stage 1 Step 1 / Step 3): 8000-char chunks, 400-char
# overlap. Reused wherever the design says "chunked like Step 1".
DEFAULT_CHUNK_SIZE = 8000
DEFAULT_CHUNK_OVERLAP = 400


@dataclass(frozen=True)
class TextChunk:
    """One chunk of source text with its exact offsets in the original."""

    index: int
    text: str
    start: int
    end: int

    @property
    def char_count(self) -> int:
        return len(self.text)


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Split ``text`` into deterministic, overlapping character chunks.

    Deterministic: chonkie's character tokenizer is a pure function of the
    input text (no randomness, no external state), so the same text always
    produces the same chunks.
    """
    if not text.strip():
        return []
    chunker = TokenChunker(
        tokenizer="character",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    raw_chunks = chunker.chunk(text)
    return [
        TextChunk(index=i, text=c.text, start=c.start_index, end=c.end_index)
        for i, c in enumerate(raw_chunks)
    ]


def reassemble_chunks(chunks: list[TextChunk]) -> str:
    """Stitch chunks back into the original text, trimming the recorded
    overlap between consecutive chunks. Used to prove zero-loss chunking.
    """
    if not chunks:
        return ""
    pieces = [chunks[0].text]
    prev_end = chunks[0].end
    for c in chunks[1:]:
        overlap = prev_end - c.start
        if overlap > 0:
            pieces.append(c.text[overlap:])
        else:
            pieces.append(c.text)
        prev_end = c.end
    return "".join(pieces)
