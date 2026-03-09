from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from persona.exceptions import InputFileError, UnsupportedFormatError
from persona.models.entities import DocumentMetadata, MapEntry, RestoreStats, TextReplacement, TextSegment


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise InputFileError(f"Input file not found: {path}") from exc
    except OSError as exc:
        raise InputFileError(f"Unable to read input file: {path}") from exc
    return digest.hexdigest()


def build_document_metadata(path: Path) -> DocumentMetadata:
    return DocumentMetadata(
        source_name=path.name,
        source_path=str(path.resolve()),
        file_format=path.suffix.lower(),
        content_sha256=compute_file_sha256(path),
    )


class FileAdapter(ABC):
    supported_suffixes: tuple[str, ...] = ()

    @abstractmethod
    def extract_segments(self, input_path: Path) -> list[TextSegment]:
        raise NotImplementedError

    @abstractmethod
    def apply_replacements(
        self,
        input_path: Path,
        output_path: Path,
        replacements_by_segment: dict[str, list[TextReplacement]],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def restore_file(
        self,
        censored_path: Path,
        output_path: Path,
        entries: list[MapEntry],
        *,
        root_key: bytes | None = None,
    ) -> RestoreStats:
        raise NotImplementedError


def get_adapter_for_path(path: Path) -> FileAdapter:
    suffix = path.suffix.lower()
    from persona.adapters.docx_adapter import DocxAdapter
    from persona.adapters.pdf_adapter import PdfAdapter
    from persona.adapters.xlsx_adapter import XlsxAdapter

    for adapter in (DocxAdapter(), XlsxAdapter(), PdfAdapter()):
        if suffix in adapter.supported_suffixes:
            return adapter
    raise UnsupportedFormatError(f"Unsupported file format '{suffix}'. Supported formats: .docx, .xlsx, .pdf")
