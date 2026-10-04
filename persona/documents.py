"""Documents as lists of text segments that can be edited in place.

`open_document(path)` returns an object with `segments` (what the engine analyses) and
`write(out, edits)` (what gets changed). Text files and PDFs (read as text) are one segment;
DOCX exposes every paragraph it can reach: body, tables, headers, footers, footnotes, comments,
text boxes, tracked deletions, field codes, hyperlink targets and document properties.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Protocol, Sequence

from lxml import etree

from persona.edits import Edit, apply_edits
from persona.engine import Segment
from persona.exceptions import InputError

TEXT_SUFFIXES = (".txt", ".md")
SUPPORTED_SUFFIXES = (*TEXT_SUFFIXES, ".pdf", ".docx")


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
    raise InputError(
        f"Unsupported file type '{path.suffix}'. For now: {', '.join(SUPPORTED_SUFFIXES)} (XLSX coming)."
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


# --------------------------------------------------------------------------------- DOCX

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
_DC = "http://purl.org/dc/elements/1.1/"
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


_PARAGRAPH_PARTS = re.compile(
    r"^word/(?:document|header\d*|footer\d*|footnotes|endnotes|comments|glossary/document)\.xml$"
)
_CUSTOM_XML_PARTS = re.compile(r"^customXml/item\d+\.xml$")
_RELS_PARTS = re.compile(r"^(?:.+/)?_rels/[^/]*\.rels$")
_NOT_INSPECTED = (
    ("word/media/", "embedded image(s)"),
    ("word/embeddings/", "embedded object(s)"),
    ("word/charts/", "chart(s)"),
    ("word/diagrams/", "diagram(s)/SmartArt"),
)

# Properties blanked on write (identity of whoever made the file), never restored.
_SCRUBBED_PROPERTIES = {
    f"{{{_CP}}}lastModifiedBy",
    f"{{{_DC}}}creator",
    f"{{{_APP}}}Company",
    f"{{{_APP}}}Manager",
    f"{{{_APP}}}HyperlinkBase",
}
_TEXT_PROPERTIES = {
    f"{{{_DC}}}title",
    f"{{{_DC}}}subject",
    f"{{{_DC}}}description",
    f"{{{_CP}}}keywords",
    f"{{{_CP}}}category",
    f"{{{_CP}}}contentStatus",
    f"{{{_VT}}}lpstr",
    f"{{{_VT}}}lpwstr",
}
_EMPTY_PEOPLE = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"/>'
)


class _Locator:
    """Where a segment lives and how to write edits back to it."""

    text: str

    def apply(self, edits: Sequence[Edit]) -> None:
        raise NotImplementedError


class _StreamLocator(_Locator):
    """Characters of one paragraph kind (live text, tracked deletions, field codes).

    Each character maps back to (w:t node, index); tabs/line breaks are virtual characters
    that keep words apart but are never edited.
    """

    def __init__(self, chars: list[tuple[etree._Element | None, int | str]], text: str) -> None:
        self._chars = chars
        self.text = text

    def apply(self, edits: Sequence[Edit]) -> None:
        pieces: dict[etree._Element, list[str]] = {}
        for node, index in self._chars:
            if node is not None and node not in pieces:
                pieces[node] = list(node.text or "")
        touched: set[etree._Element] = set()
        for edit in edits:
            covered = [(n, i) for n, i in self._chars[edit.start : edit.end] if n is not None]
            if not covered:
                continue
            for node, index in covered:
                pieces[node][index] = ""  # type: ignore[index]
                touched.add(node)
            first_node, first_index = covered[0]
            pieces[first_node][first_index] = edit.text  # type: ignore[index]
        for node in touched:
            node.text = "".join(pieces[node])
            node.set(_XML_SPACE, "preserve")


class _ValueLocator(_Locator):
    """An attribute value or an element's text."""

    def __init__(self, getter: Callable[[], str], setter: Callable[[str], None]) -> None:
        self._setter = setter
        self.text = getter()

    def apply(self, edits: Sequence[Edit]) -> None:
        self._setter(apply_edits(self.text, edits))


@dataclass(slots=True)
class _Part:
    name: str
    root: etree._Element


class DocxDocument:
    output_suffix = ".docx"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.warnings: list[str] = []
        self.segments: list[Segment] = []
        self._locators: dict[str, _Locator] = {}
        self._parts: dict[str, _Part] = {}
        self._names: list[str] = []
        self._dropped: set[str] = set()
        self._replaced: dict[str, bytes] = {}
        self._load()

    # -- loading ---------------------------------------------------------------------

    def _load(self) -> None:
        try:
            with zipfile.ZipFile(self.path) as archive:
                self._names = archive.namelist()
                if "word/document.xml" not in self._names:
                    raise InputError(f"{self.path.name} is not a valid DOCX (no word/document.xml).")
                for name in self._names:
                    if (
                        _PARAGRAPH_PARTS.match(name)
                        or _RELS_PARTS.match(name)
                        or _CUSTOM_XML_PARTS.match(name)
                        or name in {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"}
                    ):
                        self._parts[name] = _Part(name, etree.fromstring(archive.read(name)))
        except zipfile.BadZipFile as exc:
            raise InputError(f"{self.path.name} is not a valid DOCX file.") from exc
        except etree.XMLSyntaxError as exc:
            raise InputError(f"{self.path.name} contains malformed XML: {exc}") from exc
        except OSError as exc:
            raise InputError(f"Cannot read {self.path}: {exc}") from exc

        for name, part in self._parts.items():
            if _PARAGRAPH_PARTS.match(name):
                self._collect_paragraphs(part)
                self._collect_alt_text(part)
            elif _RELS_PARTS.match(name):
                self._collect_relationships(part)
            elif _CUSTOM_XML_PARTS.match(name):
                self._collect_custom_xml(part)
            else:
                self._collect_properties(part)
        self._collect_warnings()

    def _add(self, segment_id: str, locator: _Locator) -> None:
        if locator.text.strip():
            self._locators[segment_id] = locator
            self.segments.append(Segment(segment_id, locator.text))

    def _collect_paragraphs(self, part: _Part) -> None:
        for number, paragraph in enumerate(part.root.iter(_w("p"))):
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
                if not any(node is not None for node, _ in chars):
                    continue
                text = "".join(
                    (node.text or "")[i] if node is not None else i for node, i in chars  # type: ignore[index]
                )
                suffix = f":{kind}" if kind else ""
                self._add(f"{part.name}#p{number}{suffix}", _StreamLocator(chars, text))

    def _collect_alt_text(self, part: _Part) -> None:
        for number, element in enumerate(part.root.iter(f"{{{_WP}}}docPr")):
            for attribute in ("descr", "title"):
                if element.get(attribute):
                    self._add(
                        f"{part.name}#alt{number}:{attribute}",
                        _ValueLocator(
                            lambda e=element, a=attribute: e.get(a, ""),
                            lambda value, e=element, a=attribute: e.set(a, value),
                        ),
                    )

    def _collect_relationships(self, part: _Part) -> None:
        for relationship in part.root.iter(f"{{{_PKG_REL}}}Relationship"):
            if relationship.get("TargetMode") == "External":
                self._add(
                    f"{part.name}#{relationship.get('Id')}",
                    _ValueLocator(
                        lambda r=relationship: r.get("Target", ""),
                        lambda value, r=relationship: r.set("Target", value),
                    ),
                )

    def _collect_custom_xml(self, part: _Part) -> None:
        """Text stored in custom XML (SharePoint metadata, bibliography sources, form data)."""
        for number, element in enumerate(part.root.iter()):
            if isinstance(element.tag, str) and not len(element) and (element.text or "").strip():
                self._add(
                    f"{part.name}#n{number}",
                    _ValueLocator(
                        lambda e=element: e.text or "",
                        lambda value, e=element: setattr(e, "text", value),
                    ),
                )

    def _collect_properties(self, part: _Part) -> None:
        for number, element in enumerate(part.root.iter()):
            if element.tag in _TEXT_PROPERTIES and not len(element):
                self._add(
                    f"{part.name}#prop{number}",
                    _ValueLocator(
                        lambda e=element: e.text or "",
                        lambda value, e=element: setattr(e, "text", value),
                    ),
                )

    def _collect_warnings(self) -> None:
        for prefix, label in _NOT_INSPECTED:
            count = sum(1 for name in self._names if name.startswith(prefix) and not name.endswith("/"))
            if count:
                self.warnings.append(
                    f"{count} {label} in this file: text inside them is NOT anonymized. Check them by hand."
                )

    # -- writing ---------------------------------------------------------------------

    def write(self, out: Path, edits: Mapping[str, Sequence[Edit]]) -> None:
        for segment_id, segment_edits in edits.items():
            if segment_edits:
                self._locators[segment_id].apply(segment_edits)
        self._scrub()
        replaced = {name: _serialize(part.root) for name, part in self._parts.items()}
        replaced.update(self._replaced)
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.path) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                if info.filename in self._dropped:
                    continue
                data = replaced.get(info.filename, source.read(info.filename))
                target.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)

    def _scrub(self) -> None:
        """Remove who-made-this-file traces: authors, thumbnail, people list."""
        for name, part in self._parts.items():
            if _PARAGRAPH_PARTS.match(name):
                for element in part.root.iter():
                    if element.get(_w("author")):
                        element.set(_w("author"), "Author")
                    if element.get(_w("initials")):
                        element.set(_w("initials"), "A")
            elif name.startswith("docProps/"):
                for element in part.root.iter():
                    if element.tag in _SCRUBBED_PROPERTIES:
                        element.text = ""
        if "word/people.xml" in self._names:
            self._replaced["word/people.xml"] = _EMPTY_PEOPLE
        root_rels = self._parts.get("_rels/.rels")
        if root_rels is not None:
            for relationship in list(root_rels.root):
                if str(relationship.get("Type", "")).endswith("/metadata/thumbnail"):
                    self._dropped.add(relationship.get("Target", "").lstrip("/"))
                    root_rels.root.remove(relationship)


def _own_elements(paragraph: etree._Element) -> Iterator[etree._Element]:
    """Descendants of `paragraph` in document order, skipping nested paragraphs (text boxes)."""
    stack = [child for child in reversed(list(paragraph))]
    while stack:
        element = stack.pop()
        if not isinstance(element.tag, str) or element.tag == _w("p"):
            continue
        yield element
        stack.extend(reversed(list(element)))


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
