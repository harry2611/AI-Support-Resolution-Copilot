from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.config import get_settings

settings = get_settings()

SUPPORTED_FILE_TYPES = {
    ".txt": "Plain text",
    ".md": "Markdown",
    ".pdf": "PDF",
    ".docx": "Word document",
}


def parse_document_bytes(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FILE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_FILE_TYPES))
        raise ValueError(f"Unsupported file type '{suffix or 'unknown'}'. Supported types: {supported}")

    if not content:
        raise ValueError("Uploaded file is empty")

    if len(content) > settings.upload_max_file_mb * 1024 * 1024:
        raise ValueError(f"Uploaded file exceeds the {settings.upload_max_file_mb} MB limit")

    if suffix in {".txt", ".md"}:
        return _normalize_extracted_text(_decode_text(content))
    if suffix == ".pdf":
        return _normalize_extracted_text(_extract_pdf_text(content))
    if suffix == ".docx":
        return _normalize_extracted_text(_extract_docx_text(content))

    raise ValueError("Unsupported file type")


def _decode_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace").strip()


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    text_blocks = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(block for block in text_blocks if block.strip()).strip()


def _extract_docx_text(content: bytes) -> str:
    document = DocxDocument(BytesIO(content))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n\n".join(paragraphs).strip()


def _normalize_extracted_text(text: str) -> str:
    cleaned = text.replace("\u2022", "\n- ").replace("\u00a0", " ")
    cleaned = cleaned.replace("•", "\n- ")

    # Recover common PDF extraction artifacts where words are glued together.
    cleaned = _apply_until_stable(cleaned, r"(?<=[a-z])(?=[A-Z])", " ")
    cleaned = _apply_until_stable(cleaned, r"(?<=[A-Z])(?=[A-Z][a-z])", " ")
    cleaned = _apply_until_stable(cleaned, r"(?<=[a-zA-Z])(?=\d)", " ")
    cleaned = _apply_until_stable(cleaned, r"(?<=\d)(?=[A-Za-z])", " ")
    cleaned = _apply_until_stable(cleaned, r"([.,;:!?])(?=[A-Za-z])", r"\1 ")

    cleaned = "\n".join(line.strip() for line in cleaned.splitlines())
    cleaned = "\n".join(line for line in cleaned.splitlines() if line)
    cleaned = " ".join(cleaned.split()) if "\n" not in cleaned else "\n".join(" ".join(line.split()) for line in cleaned.splitlines())
    return cleaned.strip()


def _apply_until_stable(text: str, pattern: str, replacement: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = re.sub(pattern, replacement, current)
    return current
