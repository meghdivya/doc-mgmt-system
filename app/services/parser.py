from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

from docx import Document as DocxDocument
from pypdf import PdfReader


@dataclass
class ParsedPage:
    page_number: int
    text: str


def _normalize_text(text: str) -> str:
    # Collapse excessive horizontal whitespace while keeping paragraph breaks
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    cleaned_lines: list[str] = []
    blank_streak = 0
    for ln in lines:
        if not ln:
            blank_streak += 1
            if blank_streak <= 1:
                cleaned_lines.append("")
        else:
            blank_streak = 0
            cleaned_lines.append(ln)
    return "\n".join(cleaned_lines).strip()


def _extract_pdf_pages(path: Path) -> list[ParsedPage]:
    reader = PdfReader(str(path))
    pages: list[ParsedPage] = []
    for idx, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        # Handle PDFs where every word is on its own line (e.g. Skia/Google Docs exports)
        non_empty_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if len(non_empty_lines) > 25:
            avg_words = sum(len(ln.split()) for ln in non_empty_lines) / len(non_empty_lines)
            if avg_words < 1.8:
                grouped: dict[float, list[tuple[float, str]]] = defaultdict(list)

                def _visitor(txt, cm, tm, _font_dict, _font_size):
                    if txt and txt.strip():
                        y = round(cm[5] + tm[5], 1)
                        x = round(cm[4] + tm[4], 1)
                        grouped[y].append((x, txt.strip()))

                page.extract_text(visitor_text=_visitor)
                if grouped:
                    rebuilt = [
                        " ".join(tok for _x, tok in sorted(grouped[y]))
                        for y in sorted(grouped.keys(), reverse=True)
                    ]
                    raw = "\n".join(rebuilt)

        normalized = _normalize_text(raw)
        if normalized:
            pages.append(ParsedPage(page_number=idx, text=normalized))
    return pages


def _extract_docx_pages(path: Path) -> list[ParsedPage]:
    doc = DocxDocument(str(path))
    blocks: list[str] = []
    for para in doc.paragraphs:
        if para.text and para.text.strip():
            blocks.append(para.text.strip())
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))

    full_text = _normalize_text("\n\n".join(blocks))
    if not full_text:
        return []
    return _paginate_plain_text(full_text, page_chars=2800)


def _paginate_plain_text(text: str, page_chars: int = 3000) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    buffer = ""
    page_num = 1
    for para in paragraphs:
        if buffer and len(buffer) + len(para) + 2 > page_chars:
            pages.append(ParsedPage(page_number=page_num, text=buffer.strip()))
            page_num += 1
            buffer = para
        else:
            buffer = f"{buffer}\n\n{para}" if buffer else para
    if buffer.strip():
        pages.append(ParsedPage(page_number=page_num, text=buffer.strip()))
    return pages


def parse_document_file(file_path: str, file_ext: str) -> list[ParsedPage]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Stored document not found: {file_path}")

    ext = file_ext.lower()
    if ext == ".pdf":
        return _extract_pdf_pages(path)
    if ext == ".docx":
        return _extract_docx_pages(path)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw_text = path.read_text(encoding="latin-1")

    normalized = _normalize_text(raw_text)
    if not normalized:
        return []
    return _paginate_plain_text(normalized)
