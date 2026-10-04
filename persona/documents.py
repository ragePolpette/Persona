"""Documents as lists of text segments that can be edited in place.

`open_document(path)` returns an object with `segments` (what the engine analyses) and
`write(out, edits)` (what gets changed). Text files and PDFs (read as text) are one segment;
Office files (DOCX, XLSX) are edited at the XML level inside the package; see `ooxml.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol, Sequence

from persona.edits import Edit, apply_edits
from persona.engine import Segment
from persona.exceptions import InputError
from persona.office_docx import DocxDocument
from persona.office_xlsx import XlsxDocument

TEXT_SUFFIXES = (".txt", ".md")
SUPPORTED_SUFFIXES = (*TEXT_SUFFIXES, ".pdf", ".docx", ".xlsx")

__all__ = ["Document", "DocxDocument", "TextDocument", "XlsxDocument", "open_document"]


class Document(Protocol):
    path: Path
    segments: list[Segment]
    warnings: list[str]
    output_suffix: str

    def write(self, out: Path, edits: Mapping[str, Sequence[Edit]]) -> None: ...


def open_document(path: Path) -> Document:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return TextDocument(path, _read_text_file(path), output_suffix=path.suffix)
    if suffix == ".pdf":
        return TextDocument(path, _read_pdf(path), output_suffix=".txt")
    if suffix == ".docx":
        return DocxDocument(path)
    if suffix == ".xlsx":
        return XlsxDocument(path)
    raise InputError(
        f"Unsupported file type '{path.suffix}'. For now: {', '.join(SUPPORTED_SUFFIXES)} (.doc/.xls are not supported: save as .docx/.xlsx)."
    )


# --------------------------------------------------------------------------- text / PDF


class TextDocument:
    def __init__(self, path: Path, text: str, *, output_suffix: str) -> None:
        self.path = path
        self.text = text
        self.output_suffix = output_suffix
        self.segments = [Segment("text", text)]
        self.warnings: list[str] = []

    def write(self, out: Path, edits: Mapping[str, Sequence[Edit]]) -> None:
        out.write_text(apply_edits(self.text, list(edits.get("text", []))), encoding="utf-8")


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"Cannot read {path}: {exc}") from exc


def _read_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise InputError('PDF support needs an extra dependency: pip install "persona[pdf]"') from exc
    try:
        with pdfplumber.open(str(path)) as pdf:
            pages = [(page.extract_text() or "").strip() for page in pdf.pages]
    except Exception as exc:  # pdfminer raises many unrelated exception types
        raise InputError(f"Cannot read PDF {path}: {exc}") from exc
    text = "\n\n".join(page for page in pages if page)
    if not text.strip():
        raise InputError("This PDF has no extractable text (scanned?). OCR is not supported.")
    return text
