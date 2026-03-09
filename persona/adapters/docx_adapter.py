from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterator

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from persona.adapters.base import FileAdapter
from persona.core.text_ops import apply_text_replacements, strict_restore_text
from persona.models.entities import MapEntry, TextReplacement, TextSegment


class DocxAdapter(FileAdapter):
    supported_suffixes = (".docx",)

    def extract_segments(self, input_path: Path) -> list[TextSegment]:
        document = Document(str(input_path))
        return [
            TextSegment(
                segment_id=segment_id,
                location=location,
                text=paragraph.text,
                container_type="paragraph",
            )
            for segment_id, location, paragraph in self._iter_target_paragraphs(document)
            if paragraph.text
        ]

    def apply_replacements(
        self,
        input_path: Path,
        output_path: Path,
        replacements_by_segment: dict[str, list[TextReplacement]],
    ) -> None:
        document = Document(str(input_path))
        for segment_id, _, paragraph in self._iter_target_paragraphs(document):
            replacements = replacements_by_segment.get(segment_id)
            if replacements:
                self._apply_replacements_to_paragraph(paragraph, replacements)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output_path))

    def restore_file(
        self,
        censored_path: Path,
        output_path: Path,
        entries: list[MapEntry],
    ) -> tuple[int, list[str]]:
        document = Document(str(censored_path))
        entries_by_segment: dict[str, list[MapEntry]] = defaultdict(list)
        for entry in entries:
            entries_by_segment[entry.segment_id].append(entry)

        restored_count = 0
        warnings: list[str] = []
        for segment_id, _, paragraph in self._iter_target_paragraphs(document):
            segment_entries = entries_by_segment.get(segment_id)
            if not segment_entries or not paragraph.text:
                continue
            replacements, segment_warnings = self._build_restore_replacements(paragraph.text, segment_entries)
            if replacements:
                self._apply_replacements_to_paragraph(paragraph, replacements)
                restored_count += len(replacements)
            warnings.extend(segment_warnings)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output_path))
        return restored_count, warnings

    def _build_restore_replacements(
        self,
        text: str,
        entries: list[MapEntry],
    ) -> tuple[list[TextReplacement], list[str]]:
        _, warnings, _ = strict_restore_text(text, entries)
        replacements: list[TextReplacement] = []
        for entry in entries:
            cursor = 0
            while True:
                start = text.find(entry.placeholder, cursor)
                if start == -1:
                    break
                replacements.append(
                    TextReplacement(
                        start=start,
                        end=start + len(entry.placeholder),
                        replacement=entry.original_value,
                        token_id=entry.token_id,
                        entity_type=entry.entity_type,
                        original_value=entry.original_value,
                        masked_value=entry.masked_value,
                        location=entry.location,
                        segment_id=entry.segment_id,
                    )
                )
                cursor = start + len(entry.placeholder)
        return replacements, warnings

    def _iter_target_paragraphs(self, document: DocumentType) -> Iterator[tuple[str, str, Paragraph]]:
        body_index = 0
        table_index = 0
        for block in self._iter_block_items(document):
            if isinstance(block, Paragraph):
                segment_id = f"body/p{body_index}"
                yield segment_id, segment_id, block
                body_index += 1
                continue
            if isinstance(block, Table):
                yield from self._iter_table_paragraphs(block, table_index)
                table_index += 1

    def _iter_table_paragraphs(self, table: Table, table_index: int) -> Iterator[tuple[str, str, Paragraph]]:
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                for paragraph_index, paragraph in enumerate(cell.paragraphs):
                    location = f"table{table_index}/r{row_index}/c{cell_index}/p{paragraph_index}"
                    yield location, location, paragraph

    def _iter_block_items(self, parent: DocumentType | _Cell) -> Iterator[Paragraph | Table]:
        parent_element = parent.element.body if isinstance(parent, DocumentType) else parent._tc
        for child in parent_element.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def _apply_replacements_to_paragraph(self, paragraph: Paragraph, replacements: list[TextReplacement]) -> None:
        if not paragraph.runs:
            paragraph.text = apply_text_replacements(paragraph.text, replacements)
            return

        run_texts = [run.text for run in paragraph.runs]
        mapping: list[tuple[int, int]] = []
        for run_index, run_text in enumerate(run_texts):
            for char_index, _ in enumerate(run_text):
                mapping.append((run_index, char_index))

        for replacement in sorted(replacements, key=lambda item: item.start, reverse=True):
            start_run, start_char = mapping[replacement.start]
            end_run, end_char = mapping[replacement.end - 1]
            if start_run == end_run:
                current = run_texts[start_run]
                run_texts[start_run] = (
                    current[:start_char] + replacement.replacement + current[end_char + 1 :]
                )
                continue

            first_text = run_texts[start_run]
            last_text = run_texts[end_run]
            run_texts[start_run] = first_text[:start_char] + replacement.replacement
            for run_index in range(start_run + 1, end_run):
                run_texts[run_index] = ""
            run_texts[end_run] = last_text[end_char + 1 :]

        for run, new_text in zip(paragraph.runs, run_texts, strict=True):
            run.text = new_text

