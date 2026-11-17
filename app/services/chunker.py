from dataclasses import dataclass
import re

from app.services.parser import ParsedPage


@dataclass
class TextChunk:
    chunk_index: int
    page_number: int
    content: str
    token_count: int


def estimate_tokens(text: str) -> int:
    words = len(text.split())
    return max(1, int(words * 1.3)) if words else 0


def _split_into_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def chunk_pages(
    pages: list[ParsedPage],
    chunk_size_chars: int = 900,
    chunk_overlap_chars: int = 150,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    chunk_idx = 0

    for page in pages:
        units = _split_into_sentences(page.text)
        current = ""
        for unit in units:
            # Handle single extraordinarily long line without sentence breaks
            if len(unit) > chunk_size_chars:
                if current:
                    chunks.append(
                        TextChunk(
                            chunk_index=chunk_idx,
                            page_number=page.page_number,
                            content=current.strip(),
                            token_count=estimate_tokens(current),
                        )
                    )
                    chunk_idx += 1
                    current = ""
                step = max(100, chunk_size_chars - chunk_overlap_chars)
                for start in range(0, len(unit), step):
                    piece = unit[start : start + chunk_size_chars].strip()
                    if piece:
                        chunks.append(
                            TextChunk(
                                chunk_index=chunk_idx,
                                page_number=page.page_number,
                                content=piece,
                                token_count=estimate_tokens(piece),
                            )
                        )
                        chunk_idx += 1
                continue

            candidate = f"{current} {unit}".strip() if current else unit
            if len(candidate) <= chunk_size_chars:
                current = candidate
            else:
                chunks.append(
                    TextChunk(
                        chunk_index=chunk_idx,
                        page_number=page.page_number,
                        content=current.strip(),
                        token_count=estimate_tokens(current),
                    )
                )
                chunk_idx += 1
                overlap = current[-chunk_overlap_chars:].strip() if chunk_overlap_chars > 0 else ""
                current = f"{overlap} {unit}".strip() if overlap else unit

        if current.strip():
            chunks.append(
                TextChunk(
                    chunk_index=chunk_idx,
                    page_number=page.page_number,
                    content=current.strip(),
                    token_count=estimate_tokens(current),
                )
            )
            chunk_idx += 1

    return chunks
