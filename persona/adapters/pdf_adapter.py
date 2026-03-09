from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pdfplumber
from reportlab.pdfgen import canvas

from persona.adapters.base import FileAdapter
from persona.exceptions import UnsupportedFormatError
from persona.models.entities import MapEntry, TextReplacement, TextSegment


class PdfAdapter(FileAdapter):
    supported_suffixes = (".pdf",)

    def extract_segments(self, input_path: Path) -> list[TextSegment]:
        pages = self._extract_pages(input_path)
        segments: list[TextSegment] = []
        for page_index, page in enumerate(pages):
            for line_index, line in enumerate(page["lines"]):
                if line:
                    location = f"page{page_index + 1}/line{line_index + 1}"
                    segments.append(
                        TextSegment(
                            segment_id=location,
                            location=location,
                            text=line,
                            container_type="pdf_line",
                        )
                    )
        return segments

    def apply_replacements(
        self,
        input_path: Path,
        output_path: Path,
        replacements_by_segment: dict[str, list[TextReplacement]],
    ) -> None:
        pages = self._extract_pages(input_path)
        rendered_pages: list[dict[str, object]] = []
        for page_index, page in enumerate(pages):
            lines: list[str] = []
            for line_index, line in enumerate(page["lines"]):
                segment_id = f"page{page_index + 1}/line{line_index + 1}"
                replacements = replacements_by_segment.get(segment_id)
                if replacements:
                    line = self._apply_line_replacements(line, replacements)
                lines.append(line)
            rendered_pages.append({"width": page["width"], "height": page["height"], "lines": lines})
        self._write_text_pdf(output_path, rendered_pages)

    def restore_file(
        self,
        censored_path: Path,
        output_path: Path,
        entries: list[MapEntry],
    ) -> tuple[int, list[str]]:
        pages = self._extract_pages(censored_path)
        entries_by_segment: dict[str, list[MapEntry]] = defaultdict(list)
        for entry in entries:
            entries_by_segment[entry.segment_id].append(entry)

        restored_count = 0
        warnings: list[str] = []
        rendered_pages: list[dict[str, object]] = []
        for page_index, page in enumerate(pages):
            lines: list[str] = []
            for line_index, line in enumerate(page["lines"]):
                segment_id = f"page{page_index + 1}/line{line_index + 1}"
                segment_entries = entries_by_segment.get(segment_id, [])
                if segment_entries:
                    line, segment_warnings, count = self._restore_line(line, segment_entries)
                    restored_count += count
                    warnings.extend(segment_warnings)
                lines.append(line)
            rendered_pages.append({"width": page["width"], "height": page["height"], "lines": lines})
        self._write_text_pdf(output_path, rendered_pages)
        return restored_count, warnings

    def _extract_pages(self, input_path: Path) -> list[dict[str, object]]:
        pages: list[dict[str, object]] = []
        has_text = False
        with pdfplumber.open(str(input_path)) as pdf:
            for page in pdf.pages:
                extracted_text = page.extract_text() or ""
                lines = extracted_text.splitlines()
                if any(line.strip() for line in lines):
                    has_text = True
                pages.append({"width": float(page.width), "height": float(page.height), "lines": lines})
        if not has_text:
            raise UnsupportedFormatError("PDF does not contain extractable text; OCR is not supported in v1.")
        return pages

    def _apply_line_replacements(self, text: str, replacements: list[TextReplacement]) -> str:
        result = text
        for replacement in sorted(replacements, key=lambda item: item.start, reverse=True):
            result = result[: replacement.start] + replacement.replacement + result[replacement.end :]
        return result

    def _restore_line(self, text: str, entries: list[MapEntry]) -> tuple[str, list[str], int]:
        from persona.core.text_ops import strict_restore_text

        return strict_restore_text(text, entries)

    def _write_text_pdf(self, output_path: Path, pages: list[dict[str, object]]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_canvas = canvas.Canvas(str(output_path))
        for page in pages:
            width = float(page["width"])
            height = float(page["height"])
            pdf_canvas.setPageSize((width, height))
            text_object = pdf_canvas.beginText(36, height - 40)
            text_object.setFont("Helvetica", 10)
            text_object.setLeading(14)
            for line in page["lines"]:
                text_object.textLine(line)
            pdf_canvas.drawText(text_object)
            pdf_canvas.showPage()
        pdf_canvas.save()

