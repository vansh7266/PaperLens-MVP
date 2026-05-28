from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from config import MAX_PDF_PAGES, MAX_PDF_UPLOAD_MB
from core.peeler_models import Confidence, PaperChunk, PaperRecord


class PdfExtractionError(Exception):
    pass


async def extract_uploaded_pdf(filename: str, content: bytes) -> tuple[PaperRecord, list[PaperChunk]]:
    max_bytes = MAX_PDF_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise PdfExtractionError(f"PDF exceeds {MAX_PDF_UPLOAD_MB}MB limit")
    if not content.startswith(b"%PDF"):
        raise PdfExtractionError("Uploaded file is not a valid PDF")

    digest = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory(prefix="paperlens_pdf_") as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(content)
        markdown, page_count = _extract_markdown(path)

    quality = _score_quality(markdown, page_count)
    title = _guess_title(markdown) or Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    paper = PaperRecord(
        canonical_id=f"upload:{digest}",
        source_type="private_upload",
        title=title or "Uploaded paper",
        authors=[],
        abstract=markdown[:1200],
        confidence=Confidence.LOW,
        extraction_quality=quality,
        is_private=True,
    )
    chunks = _chunk_markdown(paper.canonical_id, markdown, quality)
    return paper, chunks


def _extract_markdown(path: Path) -> tuple[str, int]:
    page_count = 0
    try:
        import fitz

        doc = fitz.open(path)
        page_count = doc.page_count
        if page_count > MAX_PDF_PAGES:
            raise PdfExtractionError(f"PDF exceeds {MAX_PDF_PAGES} page limit")
        doc.close()
    except PdfExtractionError:
        raise
    except Exception as exc:
        raise PdfExtractionError(f"Could not inspect PDF: {exc}") from exc

    try:
        import pymupdf4llm

        text = pymupdf4llm.to_markdown(str(path))
        if text and len(text.strip()) > 800:
            return text, page_count
    except Exception:
        pass

    try:
        import fitz

        doc = fitz.open(path)
        text_parts = []
        for index, page in enumerate(doc, start=1):
            text_parts.append(f"\n\n# Page {index}\n\n{page.get_text()}")
        doc.close()
        text = "\n".join(text_parts)
        if len(text.strip()) < 400:
            raise PdfExtractionError("PDF has too little extractable text")
        return text, page_count
    except PdfExtractionError:
        raise
    except Exception as exc:
        raise PdfExtractionError(f"Could not extract PDF text: {exc}") from exc


def _score_quality(markdown: str, page_count: int) -> Confidence:
    chars_per_page = len(markdown) / max(page_count, 1)
    header_count = markdown.count("\n#")
    weird_ratio = sum(1 for char in markdown if ord(char) < 32 and char not in "\n\t") / max(len(markdown), 1)
    if chars_per_page > 1400 and header_count >= 3 and weird_ratio < 0.01:
        return Confidence.HIGH
    if chars_per_page > 700:
        return Confidence.MEDIUM
    return Confidence.LOW


def _guess_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        clean = line.strip(" #\t")
        if 12 <= len(clean) <= 180 and not clean.lower().startswith(("abstract", "introduction")):
            return clean
    return None


def _chunk_markdown(paper_id: str, markdown: str, quality: Confidence) -> list[PaperChunk]:
    chunks: list[PaperChunk] = []
    current_section = "Document"
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(
                PaperChunk(
                    paper_id=paper_id,
                    section=current_section,
                    text=text[:5000],
                    extraction_quality=quality,
                )
            )
        buffer.clear()

    for line in markdown.splitlines():
        if line.startswith("#") and len(line.strip("# ").strip()) > 2:
            flush()
            current_section = line.strip("# ").strip()[:120]
        else:
            buffer.append(line)
            if sum(len(item) for item in buffer) > 3500:
                flush()
    flush()
    return chunks[:80] or [
        PaperChunk(
            paper_id=paper_id,
            section="Extracted text",
            text=markdown[:5000],
            extraction_quality=quality,
        )
    ]
