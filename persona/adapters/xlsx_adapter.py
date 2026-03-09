from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

from persona.adapters.base import FileAdapter
from persona.core.text_ops import apply_text_replacements, strict_restore_text
from persona.models.entities import MapEntry, TextReplacement, TextSegment


class XlsxAdapter(FileAdapter):
    supported_suffixes = (".xlsx",)

    def extract_segments(self, input_path: Path) -> list[TextSegment]:
        workbook = load_workbook(filename=str(input_path))
        segments: list[TextSegment] = []
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and not cell.value.startswith("="):
                        location = f"{worksheet.title}!{cell.coordinate}"
                        segments.append(
                            TextSegment(
                                segment_id=location,
                                location=location,
                                text=cell.value,
                                container_type="cell",
                            )
                        )
        return segments

    def apply_replacements(
        self,
        input_path: Path,
        output_path: Path,
        replacements_by_segment: dict[str, list[TextReplacement]],
    ) -> None:
        workbook = load_workbook(filename=str(input_path))
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    location = f"{worksheet.title}!{cell.coordinate}"
                    replacements = replacements_by_segment.get(location)
                    if replacements and isinstance(cell.value, str):
                        cell.value = apply_text_replacements(cell.value, replacements)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(str(output_path))

    def restore_file(
        self,
        censored_path: Path,
        output_path: Path,
        entries: list[MapEntry],
    ) -> tuple[int, list[str]]:
        workbook = load_workbook(filename=str(censored_path))
        entries_by_segment: dict[str, list[MapEntry]] = defaultdict(list)
        for entry in entries:
            entries_by_segment[entry.segment_id].append(entry)

        restored_count = 0
        warnings: list[str] = []
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    location = f"{worksheet.title}!{cell.coordinate}"
                    segment_entries = entries_by_segment.get(location)
                    if not segment_entries or not isinstance(cell.value, str):
                        continue
                    restored_text, segment_warnings, count = strict_restore_text(cell.value, segment_entries)
                    if count:
                        cell.value = restored_text
                        restored_count += count
                    warnings.extend(segment_warnings)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(str(output_path))
        return restored_count, warnings

