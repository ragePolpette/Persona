"""Turn an input file into text. PDFs are read as extracted text; the output is plain text.

Scanned (image-only) PDFs are rejected: there is no OCR.
"""

from __future__ import annotations

from pathlib import Path

from persona.exceptions import InputError

TEXT_SUFFIXES = (".txt", ".md")
PDF_SUFFIX = ".pdf"
SUPPORTED_SUFFIXES = (*TEXT_SUFFIXES, PDF_SUFFIX)


def output_suffix(path: Path) -> str:
    """Anonymized/restored PDFs are written as .txt: the text is all we keep."""
    return ".txt" if path.suffix.lower() == PDF_SUFFIX else path.suffix


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InputError(f"Cannot read {path}: {exc}") from exc
    if suffix == PDF_SUFFIX:
        return _read_pdf(path)
    raise InputError(
        f"Unsupported file type '{path.suffix}'. For now: {', '.join(SUPPORTED_SUFFIXES)} (DOCX/XLSX coming)."
    )


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
