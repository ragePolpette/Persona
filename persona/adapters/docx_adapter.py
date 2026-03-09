from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterator

from docx import Document
from docx.document import Document as DocumentType
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from persona.adapters.base import FileAdapter
from persona.core.text_ops import apply_text_replacements, strict_restore_text
from persona.exceptions import DocumentProcessingError, InputFileError
from persona.models.entities import MapEntry, RestoreStats, TextReplacement, TextSegment


class DocxAdapter(FileAdapter):
    supported_suffixes = (".docx",)

    def extract_segments(self, input_path: Path) -> list[TextSegment]:
        document = self._open_document(input_path)
        try:
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
        except Exception as exc:
            raise DocumentProcessingError("Unable to extract text segments from DOCX input.") from exc

    def apply_replacements(
        self,
        input_path: Path,
        output_path: Path,
        replacements_by_segment: dict[str, list[TextReplacement]],
    ) -> None:
        document = self._open_document(input_path)
        try:
            for segment_id, _, paragraph in self._iter_target_paragraphs(document):
                replacements = replacements_by_segment.get(segment_id)
                if replacements:
                    self._apply_replacements_to_paragraph(paragraph, replacements)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(output_path))
        except Exception as exc:
            raise DocumentProcessingError("Unable to write anonymized DOCX output.") from exc

    def restore_file(
        self,
        censored_path: Path,
        output_path: Path,
        entries: list[MapEntry],
        *,
        root_key: bytes | None = None,
    ) -> RestoreStats:
        document = self._open_document(censored_path)
        entries_by_segment: dict[str, list[MapEntry]] = defaultdict(list)
        for entry in entries:
            entries_by_segment[entry.segment_id].append(entry)

        stats = RestoreStats()
        try:
            for segment_id, location, paragraph in self._iter_target_paragraphs(document):
                segment_entries = entries_by_segment.get(segment_id)
                if not segment_entries or not paragraph.text:
                    continue
                outcome = strict_restore_text(
                    paragraph.text,
                    segment_entries,
                    root_key=root_key,
                    segment_id=segment_id,
                    location=location,
                )
                if outcome.text != paragraph.text:
                    self._apply_replacements_to_paragraph(
                        paragraph,
                        [
                            TextReplacement(
                                start=0,
                                end=len(paragraph.text),
                                replacement=outcome.text,
                                token_id="",
                                entity_type="",
                                original_value="",
                                masked_value="",
                                location=location,
                                segment_id=segment_id,
                            )
                        ],
                    )
                stats.extend(outcome.stats)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(output_path))
        except Exception as exc:
            raise DocumentProcessingError("Unable to restore DOCX output.") from exc
        return stats

    def _open_document(self, input_path: Path) -> DocumentType:
        try:
            return Document(str(input_path))
        except FileNotFoundError as exc:
            raise InputFileError(f"DOCX file not found: {input_path}") from exc
        except PackageNotFoundError as exc:
            raise InputFileError(f"DOCX file is missing or not a valid Office package: {input_path}") from exc
        except Exception as exc:
            raise DocumentProcessingError(f"Unable to open DOCX file: {input_path}") from exc

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
