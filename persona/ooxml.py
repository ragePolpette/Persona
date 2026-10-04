"""Shared machinery for Office Open XML packages (DOCX, XLSX): locators, zip rewriting, scrubbing.

A package is a zip of XML parts. We parse only the parts that can hold text, expose their text
as segments, apply position-based edits to the XML nodes, and copy every other entry untouched.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from lxml import etree

from persona.edits import Edit, apply_edits
from persona.engine import Segment
from persona.exceptions import InputError

VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
DC = "http://purl.org/dc/elements/1.1/"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

RELS_PARTS = re.compile(r"^(?:.+/)?_rels/[^/]*\.rels$")
DOC_PROPS = {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"}

# Identity of whoever made the file: blanked on write, never restored.
SCRUBBED_PROPERTIES = {
    f"{{{CP}}}lastModifiedBy",
    f"{{{DC}}}creator",
    f"{{{APP}}}Company",
    f"{{{APP}}}Manager",
    f"{{{APP}}}HyperlinkBase",
}
TEXT_PROPERTIES = {
    f"{{{DC}}}title",
    f"{{{DC}}}subject",
    f"{{{DC}}}description",
    f"{{{CP}}}keywords",
    f"{{{CP}}}category",
    f"{{{CP}}}contentStatus",
    f"{{{VT}}}lpstr",
    f"{{{VT}}}lpwstr",
}


def strip_brackets(text: str) -> str:
    """`[AZIENDA_1]` -> `AZIENDA_1`: sheet names and formulas cannot contain square brackets."""
    return text.replace("[", "").replace("]", "")


class Locator:
    """Where a segment lives and how to write edits back to it."""

    text: str

    def apply(self, edits: Sequence[Edit]) -> None:
        raise NotImplementedError


class StreamLocator(Locator):
    """Characters spread over several text nodes (runs). Each maps back to (node, index).

    Virtual characters (tabs, line breaks) have no node: they keep words apart, never edited.
    """

    def __init__(
        self,
        chars: list[tuple[etree._Element | None, int | str]],
        *,
        transform: Callable[[str], str] | None = None,
    ) -> None:
        self._chars = chars
        self._transform = transform
        self.text = "".join(
            (node.text or "")[i] if node is not None else i  # type: ignore[index]
            for node, i in chars
        )

    def apply(self, edits: Sequence[Edit]) -> None:
        pieces: dict[etree._Element, list[str]] = {}
        for node, _ in self._chars:
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
            pieces[first_node][first_index] = (  # type: ignore[index]
                self._transform(edit.text) if self._transform else edit.text
            )
        for node in touched:
            node.text = "".join(pieces[node])
            node.set(XML_SPACE, "preserve")


class ValueLocator(Locator):
    """An attribute value or an element's text."""

    def __init__(
        self,
        getter: Callable[[], str],
        setter: Callable[[str], None],
        *,
        transform: Callable[[str], str] | None = None,
    ) -> None:
        self._setter = setter
        self._transform = transform
        self.text = getter()

    def apply(self, edits: Sequence[Edit]) -> None:
        if self._transform:
            edits = [Edit(e.start, e.end, self._transform(e.text)) for e in edits]
        self._setter(apply_edits(self.text, edits))


@dataclass(slots=True)
class Part:
    name: str
    root: etree._Element


class OoxmlPackage:
    """Base for DOCX/XLSX. Subclasses say which parts to parse, collect segments, and scrub."""

    output_suffix = ""
    kind = "Office"
    required_part = ""
    # (zip path prefix, label): present => warning that its text is not anonymized
    not_inspected: tuple[tuple[str, str], ...] = ()
    # extra zip prefixes whose raw bytes are loaded (for subclass warnings), without a generic warning
    scan_raw: tuple[str, ...] = ()

    def __init__(self, path: Path) -> None:
        self.path = path
        self.warnings: list[str] = []
        self.segments: list[Segment] = []
        self._locators: dict[str, Locator] = {}
        self._parts: dict[str, Part] = {}
        self._names: list[str] = []
        self._dropped: set[str] = set()
        self._replaced: dict[str, bytes] = {}
        self._load()

    # -- hooks -----------------------------------------------------------------------

    def wants_part(self, name: str) -> bool:
        raise NotImplementedError

    def collect(self, part: Part) -> None:
        raise NotImplementedError

    def scrub_part(self, part: Part) -> None:
        pass

    def extra_warnings(self) -> None:
        pass

    def properties_transform(self) -> Callable[[str], str] | None:
        return None

    # -- loading ---------------------------------------------------------------------

    def _load(self) -> None:
        try:
            with zipfile.ZipFile(self.path) as archive:
                self._names = archive.namelist()
                if self.required_part not in self._names:
                    raise InputError(
                        f"{self.path.name} is not a valid {self.kind} (no {self.required_part})."
                    )
                for name in self._names:
                    if RELS_PARTS.match(name) or name in DOC_PROPS or self.wants_part(name):
                        self._parts[name] = Part(name, etree.fromstring(archive.read(name)))
                self._raw = {
                    name: archive.read(name)
                    for name in self._names
                    if any(name.startswith(prefix) for prefix, _ in self.not_inspected)
                    or any(name.startswith(prefix) for prefix in self.scan_raw)
                    or name.endswith(".bin")
                }
        except zipfile.BadZipFile as exc:
            raise InputError(f"{self.path.name} is not a valid {self.kind} file.") from exc
        except etree.XMLSyntaxError as exc:
            raise InputError(f"{self.path.name} contains malformed XML: {exc}") from exc
        except OSError as exc:
            raise InputError(f"Cannot read {self.path}: {exc}") from exc

        for name, part in self._parts.items():
            if RELS_PARTS.match(name):
                self._collect_relationships(part)
            elif name in DOC_PROPS:
                self._collect_properties(part)
            else:
                self.collect(part)
        self._collect_warnings()
        self.extra_warnings()

    def add(self, segment_id: str, locator: Locator) -> None:
        if locator.text.strip():
            self._locators[segment_id] = locator
            self.segments.append(Segment(segment_id, locator.text))

    def add_attribute(
        self, segment_id: str, element: etree._Element, attribute: str, *, transform=None
    ) -> None:
        if element.get(attribute):
            self.add(
                segment_id,
                ValueLocator(
                    lambda: element.get(attribute, ""),
                    lambda value: element.set(attribute, value),
                    transform=transform,
                ),
            )

    def add_text(self, segment_id: str, element: etree._Element, *, transform=None) -> None:
        self.add(
            segment_id,
            ValueLocator(
                lambda: element.text or "",
                lambda value: setattr(element, "text", value),
                transform=transform,
            ),
        )

    def _collect_relationships(self, part: Part) -> None:
        for relationship in part.root.iter(f"{{{PKG_REL}}}Relationship"):
            if relationship.get("TargetMode") == "External":
                self.add_attribute(f"{part.name}#{relationship.get('Id')}", relationship, "Target")

    def _collect_properties(self, part: Part) -> None:
        transform = self.properties_transform()
        for number, element in enumerate(part.root.iter()):
            if element.tag in TEXT_PROPERTIES and not len(element):
                self.add_text(
                    f"{part.name}#prop{number}",
                    element,
                    transform=transform if element.tag == f"{{{VT}}}lpstr" else None,
                )

    def _collect_warnings(self) -> None:
        for prefix, label in self.not_inspected:
            count = sum(1 for name in self._names if name.startswith(prefix) and not name.endswith("/"))
            if count:
                self.warnings.append(
                    f"{count} {label} in this file: text inside them is NOT anonymized. Check them by hand."
                )
        if any(name.endswith(".bin") and "vbaProject" in name for name in self._names):
            self.warnings.append("This file contains macros (VBA): they are NOT inspected or anonymized.")

    # -- writing ---------------------------------------------------------------------

    def write(self, out: Path, edits: Mapping[str, Sequence[Edit]]) -> None:
        for segment_id, segment_edits in edits.items():
            if segment_edits:
                self._locators[segment_id].apply(segment_edits)
        self._scrub()
        replaced = {name: serialize(part.root) for name, part in self._parts.items()}
        replaced.update(self._replaced)
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.path) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                if info.filename in self._dropped:
                    continue
                data = replaced.get(info.filename, source.read(info.filename))
                target.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)

    def _scrub(self) -> None:
        """Remove who-made-this-file traces: properties, thumbnail, plus format-specific ones."""
        for name, part in self._parts.items():
            if name.startswith("docProps/"):
                for element in part.root.iter():
                    if element.tag in SCRUBBED_PROPERTIES:
                        element.text = ""
            self.scrub_part(part)
        root_rels = self._parts.get("_rels/.rels")
        if root_rels is not None:
            for relationship in list(root_rels.root):
                if str(relationship.get("Type", "")).endswith("/metadata/thumbnail"):
                    self._dropped.add(relationship.get("Target", "").lstrip("/"))
                    root_rels.root.remove(relationship)


def serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
