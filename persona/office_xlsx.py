"""XLSX: shared and inline strings, formulas, cached string results, sheet names, defined names,
hyperlinks, headers/footers, validation texts, comments (legacy and threaded), table column
names and document properties.

Sheet names and formulas cannot hold square brackets, so edits there use the bracket-less form
(`AZIENDA_1`). Everything else gets the normal `[AZIENDA_1]`. The restore reads both.
"""

from __future__ import annotations

import posixpath
import re

from lxml import etree

from persona.ooxml import OoxmlPackage, Part, StreamLocator, strip_brackets

_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_TC = "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"
_DRAWING_TEXT = b"<a:t>"
_MAX_SHEET_NAME = 31


def _s(tag: str) -> str:
    return f"{{{_S}}}{tag}"


_PARTS = re.compile(
    r"^(?:xl/(?:sharedStrings|workbook)\.xml"
    r"|xl/worksheets/sheet\d+\.xml"
    r"|xl/comments(?:/[^/]+|\d*)\.xml"
    r"|xl/threadedComments/threadedComment\d+\.xml"
    r"|xl/persons/person\d*\.xml"
    r"|xl/tables/table\d+\.xml"
    r"|customXml/item\d+\.xml)$"
)
_HEADER_FOOTER = ("oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter")
_BIG_INTEGER = re.compile(r"^\d{9,12}$")


class _StringLocator(StreamLocator):
    """A shared/inline string. Phonetic guides (rPh) describe the original text, so once the text
    is edited they are stale and would reveal what was masked: drop them."""

    def __init__(self, container: etree._Element, chars) -> None:
        super().__init__(chars)
        self._container = container

    def apply(self, edits) -> None:
        super().apply(edits)
        if edits:
            for phonetic in list(self._container.iter(_s("rPh"))):
                phonetic.getparent().remove(phonetic)


class XlsxDocument(OoxmlPackage):
    output_suffix = ".xlsx"
    kind = "XLSX"
    required_part = "xl/workbook.xml"
    not_inspected = (
        ("xl/media/", "embedded image(s)"),
        ("xl/embeddings/", "embedded object(s)"),
        ("xl/charts/", "chart(s)"),
        ("xl/pivotCache/", "pivot cache(s)"),
        ("xl/pivotTables/", "pivot table(s)"),
        ("xl/externalLinks/", "external workbook link(s)"),
        ("xl/connections.xml", "data connection(s)"),
        ("xl/queryTables/", "query table(s)"),
        ("xl/diagrams/", "diagram(s)/SmartArt"),
    )
    scan_raw = ("xl/drawings/",)

    def __init__(self, path):
        self._numeric_ids: list[tuple[str, str]] = []
        super().__init__(path)

    def wants_part(self, name: str) -> bool:
        return bool(_PARTS.match(name))

    def properties_transform(self):
        return strip_brackets  # TitlesOfParts mirrors the sheet names

    # -- collecting ------------------------------------------------------------------

    def collect(self, part: Part) -> None:
        name = part.name
        if name == "xl/sharedStrings.xml":
            self._collect_shared_strings(part)
        elif name == "xl/workbook.xml":
            self._collect_workbook(part)
        elif name.startswith("xl/worksheets/"):
            self._collect_worksheet(part)
        elif name.startswith("xl/comments"):
            self._collect_comments(part)
        elif name.startswith("xl/threadedComments/"):
            for number, element in enumerate(part.root.iter(f"{{{_TC}}}text")):
                self.add_text(f"{name}#t{number}", element)
        elif name.startswith("xl/tables/"):
            for number, element in enumerate(part.root.iter(_s("tableColumn"))):
                self.add_attribute(f"{name}#col{number}", element, "name")
        elif name.startswith("customXml/"):
            for number, element in enumerate(part.root.iter()):
                if isinstance(element.tag, str) and not len(element) and (element.text or "").strip():
                    self.add_text(f"{name}#n{number}", element)

    def _rich_text_chars(self, container: etree._Element) -> list[tuple[etree._Element | None, int | str]]:
        """Characters of a shared/inline string, without phonetic runs (rPh)."""
        nodes: list[etree._Element] = []
        for child in container:
            if child.tag == _s("t"):
                nodes.append(child)
            elif child.tag == _s("r"):
                nodes.extend(child.findall(_s("t")))
        return [(node, i) for node in nodes for i in range(len(node.text or ""))]

    def _phonetic_chars(self, container: etree._Element) -> list[tuple[etree._Element | None, int | str]]:
        nodes = [t for ph in container.iter(_s("rPh")) for t in ph.findall(_s("t"))]
        return [(node, i) for node in nodes for i in range(len(node.text or ""))]

    def _add_string(self, segment_id: str, container: etree._Element) -> None:
        main = self._rich_text_chars(container)
        if main:
            self.add(segment_id, _StringLocator(container, main))
        phonetic = self._phonetic_chars(container)
        if phonetic:
            self.add(f"{segment_id}:ph", StreamLocator(phonetic))

    def _collect_shared_strings(self, part: Part) -> None:
        for number, item in enumerate(part.root.findall(_s("si"))):
            self._add_string(f"{part.name}#s{number}", item)

    def _collect_workbook(self, part: Part) -> None:
        for number, sheet in enumerate(part.root.iter(_s("sheet"))):
            self.add_attribute(f"{part.name}#sheet{number}", sheet, "name", transform=strip_brackets)
        for number, defined in enumerate(part.root.iter(_s("definedName"))):
            self.add_text(f"{part.name}#name{number}", defined, transform=strip_brackets)

    def _collect_worksheet(self, part: Part) -> None:
        root, name = part.root, part.name
        for cell in root.iter(_s("c")):
            ref = cell.get("r", "?")
            kind = cell.get("t")
            if kind == "inlineStr":
                inline = cell.find(_s("is"))
                if inline is not None:
                    self._add_string(f"{name}#{ref}", inline)
            formula = cell.find(_s("f"))
            if formula is not None and (formula.text or "").strip():
                self.add_text(f"{name}#{ref}:f", formula, transform=strip_brackets)
            value = cell.find(_s("v"))
            if value is not None:
                if kind == "str":
                    self.add_text(f"{name}#{ref}:v", value)
                elif kind in (None, "n") and _BIG_INTEGER.match((value.text or "").strip()):
                    self._numeric_ids.append((name, ref))
        for number, link in enumerate(root.iter(_s("hyperlink"))):
            self.add_attribute(f"{name}#link{number}:display", link, "display")
            self.add_attribute(f"{name}#link{number}:tooltip", link, "tooltip")
            self.add_attribute(f"{name}#link{number}:location", link, "location", transform=strip_brackets)
        for tag in _HEADER_FOOTER:
            for number, element in enumerate(root.iter(_s(tag))):
                self.add_text(f"{name}#{tag}{number}", element)
        for number, validation in enumerate(root.iter(_s("dataValidation"))):
            for attribute in ("prompt", "promptTitle", "error", "errorTitle"):
                self.add_attribute(f"{name}#dv{number}:{attribute}", validation, attribute)
        for tag in ("formula1", "formula2", "formula"):
            for number, element in enumerate(root.iter(_s(tag))):
                self.add_text(f"{name}#{tag}{number}", element, transform=strip_brackets)

    def _collect_comments(self, part: Part) -> None:
        for number, comment in enumerate(part.root.iter(_s("comment"))):
            text = comment.find(_s("text"))
            if text is not None:
                self._add_string(f"{part.name}#c{number}", text)

    # -- warnings / scrubbing -----------------------------------------------------------

    def extra_warnings(self) -> None:
        for name, data in self._raw.items():
            if name.startswith("xl/drawings/") and _DRAWING_TEXT in data:
                self.warnings.append("Text boxes or shapes in drawings are NOT anonymized. Check them by hand.")
                break
        if self._numeric_ids:
            names = self._sheet_names_by_part()
            examples = ", ".join(f"{names.get(part, part)}!{ref}" for part, ref in self._numeric_ids[:3])
            self.warnings.append(
                f"{len(self._numeric_ids)} numeric cell(s) hold 9-12 digit numbers (phone, P.IVA or tax code "
                f"stored as numbers?) and are NOT anonymized, e.g. {examples}. Check them by hand."
            )

    def _sheet_names_by_part(self) -> dict[str, str]:
        workbook = self._parts.get("xl/workbook.xml")
        rels = self._parts.get("xl/_rels/workbook.xml.rels")
        if workbook is None or rels is None:
            return {}
        targets = {r.get("Id"): r.get("Target", "") for r in rels.root.iter(f"{{{_PKG_REL}}}Relationship")}
        mapping: dict[str, str] = {}
        for sheet in workbook.root.iter(_s("sheet")):
            target = targets.get(sheet.get(f"{{{_R}}}id"), "")
            if target:
                full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")
                mapping[full] = sheet.get("name", "")
        return mapping

    def scrub_part(self, part: Part) -> None:
        name = part.name
        if name == "xl/workbook.xml":
            for element in part.root.iter(_s("fileSharing")):
                if element.get("userName"):
                    element.set("userName", "Author")
            for sheet in part.root.iter(_s("sheet")):
                if len(sheet.get("name", "")) > _MAX_SHEET_NAME:
                    self.warnings.append(
                        f"A sheet name exceeds {_MAX_SHEET_NAME} characters after anonymization: Excel may "
                        "refuse to open the file."
                    )
        elif name.startswith("xl/comments"):
            for author in part.root.iter(_s("author")):
                author.text = "Author"
        elif name.startswith("xl/persons/"):
            for person in part.root.iter():
                if person.get("displayName"):
                    person.set("displayName", "Author")
                if person.get("userId"):
                    person.set("userId", "author")
