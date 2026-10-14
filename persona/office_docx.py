"""DOCX: paragraphs of the body, tables, headers, footers, notes, comments, text boxes, tracked
deletions, field codes, hyperlink targets, alt text, custom XML and document properties."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from lxml import etree

from persona.detect.columns import header_kind
from persona.ooxml import OoxmlPackage, Part, StreamLocator

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


_PARAGRAPH_PARTS = re.compile(
    r"^word/(?:document|header\d*|footer\d*|footnotes|endnotes|comments|glossary/document)\.xml$"
)
_CUSTOM_XML_PARTS = re.compile(r"^customXml/item\d+\.xml$")
_EMPTY_PEOPLE = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"/>'
)


class DocxDocument(OoxmlPackage):
    output_suffix = ".docx"
    kind = "DOCX"
    required_part = "word/document.xml"
    not_inspected = (
        ("word/media/", "embedded image(s)"),
        ("word/embeddings/", "embedded object(s)"),
        ("word/charts/", "chart(s)"),
        ("word/diagrams/", "diagram(s)/SmartArt"),
    )

    def __init__(self, path: Path) -> None:
        self._paragraph_ids: dict[etree._Element, str] = {}
        super().__init__(path)

    def wants_part(self, name: str) -> bool:
        return bool(_PARAGRAPH_PARTS.match(name) or _CUSTOM_XML_PARTS.match(name))

    def collect(self, part: Part) -> None:
        if _PARAGRAPH_PARTS.match(part.name):
            self._collect_paragraphs(part)
            self._collect_alt_text(part)
        else:
            self._collect_custom_xml(part)

    def _collect_paragraphs(self, part: Part) -> None:
        for number, paragraph in enumerate(part.root.iter(_w("p"))):
            self._paragraph_ids[paragraph] = f"{part.name}#p{number}"
            streams: dict[str, list[tuple[etree._Element | None, int | str]]] = {"": [], "del": [], "field": []}
            for element in _own_elements(paragraph):
                tag = element.tag
                if tag == _w("t"):
                    streams[""].extend((element, i) for i in range(len(element.text or "")))
                elif tag == _w("delText"):
                    streams["del"].extend((element, i) for i in range(len(element.text or "")))
                elif tag == _w("instrText"):
                    streams["field"].extend((element, i) for i in range(len(element.text or "")))
                elif tag == _w("tab"):
                    streams[""].append((None, "\t"))
                elif tag in (_w("br"), _w("cr")):
                    streams[""].append((None, "\n"))
            for kind, chars in streams.items():
                if any(node is not None for node, _ in chars):
                    suffix = f":{kind}" if kind else ""
                    self.add(f"{part.name}#p{number}{suffix}", StreamLocator(chars))

    def _collect_alt_text(self, part: Part) -> None:
        for number, element in enumerate(part.root.iter(f"{{{_WP}}}docPr")):
            for attribute in ("descr", "title"):
                self.add_attribute(f"{part.name}#alt{number}:{attribute}", element, attribute)

    def _collect_custom_xml(self, part: Part) -> None:
        """Text stored in custom XML (SharePoint metadata, bibliography sources, form data)."""
        for number, element in enumerate(part.root.iter()):
            if isinstance(element.tag, str) and not len(element) and (element.text or "").strip():
                self.add_text(f"{part.name}#n{number}", element)

    def assign_column_kinds(self) -> None:
        """Below a first table row such as "Nome | Email | P.IVA", every paragraph in those columns is sensitive."""
        by_id = {segment.id: segment for segment in self.segments}
        for name, part in self._parts.items():
            if not _PARAGRAPH_PARTS.match(name):
                continue
            for table in part.root.iter(_w("tbl")):
                rows = table.findall(_w("tr"))
                if len(rows) < 2:
                    continue
                kinds: dict[int, str] = {}
                for column, cell in _grid_cells(rows[0]):
                    text = " ".join(
                        by_id[sid].text for p in cell.iter(_w("p")) if (sid := self._paragraph_ids.get(p)) in by_id
                    )
                    kind = header_kind(text)
                    if kind:
                        kinds[column] = kind
                if not kinds:
                    continue
                for row in rows[1:]:
                    for column, cell in _grid_cells(row):
                        if column not in kinds:
                            continue
                        for paragraph in cell.iter(_w("p")):
                            segment = by_id.get(self._paragraph_ids.get(paragraph, ""))
                            if segment is not None and segment.column_kind is None:
                                segment.column_kind = kinds[column]

    def scrub_part(self, part: Part) -> None:
        if _PARAGRAPH_PARTS.match(part.name):
            for element in part.root.iter():
                if element.get(_w("author")):
                    element.set(_w("author"), "Author")
                if element.get(_w("initials")):
                    element.set(_w("initials"), "A")

    def _scrub(self) -> None:
        super()._scrub()
        if "word/people.xml" in self._names:
            self._replaced["word/people.xml"] = _EMPTY_PEOPLE


def _grid_cells(row: etree._Element) -> Iterator[tuple[int, etree._Element]]:
    """(grid column, cell) for the cells of a table row, counting merged cells (gridSpan)."""
    column = 0
    for cell in row.findall(_w("tc")):
        yield column, cell
        span = cell.find(f"{_w('tcPr')}/{_w('gridSpan')}")
        value = span.get(_w("val"), "1") if span is not None else "1"
        column += int(value) if value.isdigit() and int(value) > 0 else 1


def _own_elements(paragraph: etree._Element) -> Iterator[etree._Element]:
    """Descendants of `paragraph` in document order, skipping nested paragraphs (text boxes)."""
    stack = [child for child in reversed(list(paragraph))]
    while stack:
        element = stack.pop()
        if not isinstance(element.tag, str) or element.tag == _w("p"):
            continue
        yield element
        stack.extend(reversed(list(element)))
