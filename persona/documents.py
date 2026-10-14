"""Documents as lists of text segments that can be edited in place.

`open_document(path)` returns an object with `segments` (what the engine analyses) and
`write(out, edits)` (what gets changed). Text files and PDFs (read as text) are one segment;
Office files (DOCX, XLSX) are edited at the XML level inside the package; see `ooxml.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from persona.edits import Edit, apply_edits
from persona.engine import Segment
from persona.exceptions import InputError
from persona.office_docx import DocxDocument
from persona.office_xlsx import XlsxDocument

TEXT_SUFFIXES = (".txt", ".md")
SUPPORTED_SUFFIXES = (*TEXT_SUFFIXES, ".pdf", ".docx", ".xlsx")

__all__ = ["Document", "DocxDocument", "TextDocument", "XlsxDocument", "decode_text", "open_document"]


class Document(Protocol):
    path: Path
    segments: list[Segment]
    warnings: list[str]
    output_suffix: str

    def write(self, out: Path, edits: Mapping[str, Sequence[Edit]]) -> None: ...


def open_document(path: Path) -> Document:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        text, bom = _read_text_file(path)
        return TextDocument(path, text, output_suffix=path.suffix, bom=bom)
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
    """Line endings are kept as they are (no newline translation) and a UTF-8 BOM is written back."""

    def __init__(self, path: Path, text: str, *, output_suffix: str, bom: bool = False) -> None:
        self.path = path
        self.text = text
        self.output_suffix = output_suffix
        self.bom = bom
        self.segments = [Segment("text", text)]
        self.warnings: list[str] = []

    def render(self, edits: Mapping[str, Sequence[Edit]]) -> str:
        return apply_edits(self.text, list(edits.get("text", [])))

    def write(self, out: Path, edits: Mapping[str, Sequence[Edit]]) -> None:
        with open(out, "w", encoding="utf-8-sig" if self.bom else "utf-8", newline="") as handle:
            handle.write(self.render(edits))


def decode_text(data: bytes) -> tuple[str, bool]:
    """(text, had a UTF-8 BOM). UTF-8 first, then Windows-1252, the usual encoding of legacy Italian files."""
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        return data.decode("utf-8-sig"), bom
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), False
    except UnicodeDecodeError as exc:
        raise InputError(f"Unknown text encoding (not UTF-8 or Windows-1252): {exc}") from exc


def _read_text_file(path: Path) -> tuple[str, bool]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputError(f"Cannot read {path}: {exc}") from exc
    try:
        return decode_text(data)
    except InputError as exc:
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
