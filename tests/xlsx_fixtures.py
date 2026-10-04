"""Builds XLSX files that hide sensitive data in the places real workbooks do."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

SENSITIVE = [
    "Acme S.r.l.",
    "Mario Rossi",
    "mario.rossi@example.test",
    "338 4567890",
    "Giulia Marchetti",
]
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def build_xlsx(path: Path, *, with_chart_and_drawing: bool = False) -> Path:
    wb = Workbook()
    wb.properties.creator = "Mario Rossi"
    wb.properties.lastModifiedBy = "Giulia Marchetti"
    wb.properties.title = "Fatture Acme S.r.l."

    clients = wb.active
    clients.title = "Acme S.r.l."
    clients.append(["Cliente", "Referente", "Telefono", "Email", "Importo", "Cellulare"])
    clients.append(["Acme S.r.l.", "Dott. Mario Rossi", "338 4567890", "mario.rossi@example.test", 12500, 3384567890])
    clients["A2"].comment = Comment("Chiamare Mario Rossi prima di venerdì", "Giulia Marchetti")
    clients["B2"].hyperlink = "mailto:mario.rossi@example.test"
    clients.column_dimensions["A"].width = 33
    clients.oddHeader.center.text = "Riservato - Mario Rossi"
    validation = DataValidation(type="list", formula1='"Acme S.r.l.,Beta S.p.A."', prompt="Scegli Acme S.r.l.")
    clients.add_data_validation(validation)
    validation.add("A5")

    summary = wb.create_sheet("Riepilogo")
    summary["A1"] = "Totale"
    summary["B1"] = "='Acme S.r.l.'!E2*2"
    summary["A2"] = "Valori business"
    summary["B2"] = "30 giorni"
    wb.defined_names["Cliente1"] = DefinedName("Cliente1", attr_text="'Acme S.r.l.'!$A$2")

    wb.save(str(path))
    _inject(path, with_chart_and_drawing)
    return path


def _inject(path: Path, with_chart_and_drawing: bool) -> None:
    with zipfile.ZipFile(path) as source:
        order = source.namelist()
        entries = {name: source.read(name) for name in order}

    sheet = entries["xl/worksheets/sheet1.xml"].decode("utf-8")
    inline_row = (
        '<row r="9"><c r="A9" t="inlineStr"><is><t>Referente Giulia Marchetti</t></is></c></row>'
    )
    shared_rows = (
        '<row r="10"><c r="A10" t="s"><v>0</v></c></row><row r="11"><c r="A11" t="s"><v>1</v></c></row>'
    )
    entries["xl/worksheets/sheet1.xml"] = sheet.replace(
        "</sheetData>", inline_row + shared_rows + "</sheetData>", 1
    ).encode("utf-8")

    # a real sharedStrings part: rich text split over runs, and a phonetic run
    entries["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst xmlns="{S_NS}" count="2" uniqueCount="2">'
        '<si><r><rPr><b/></rPr><t xml:space="preserve">Mario </t></r><r><t>Rossi</t></r></si>'
        '<si><t>Contratto Giulia Marchetti</t><rPh sb="0" eb="1"><t>ジュリア</t></rPh></si>'
        "</sst>"
    ).encode("utf-8")
    workbook_rels = entries["xl/_rels/workbook.xml.rels"].decode("utf-8").replace(
        "</Relationships>",
        '<Relationship Id="rIdSS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>',
    )
    entries["xl/_rels/workbook.xml.rels"] = workbook_rels.encode("utf-8")
    content_types = entries["[Content_Types].xml"].decode("utf-8").replace(
        "</Types>",
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
    )
    entries["[Content_Types].xml"] = content_types.encode("utf-8")

    entries["xl/threadedComments/threadedComment1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ThreadedComments xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments">'
        '<threadedComment ref="A2" personId="{1}" id="{2}"><text>Sentire Mario Rossi</text></threadedComment>'
        "</ThreadedComments>"
    ).encode("utf-8")
    entries["xl/persons/person.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<personList xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments">'
        '<person displayName="Mario Rossi" id="{1}" userId="mario.rossi@example.test" providerId="AD"/>'
        "</personList>"
    ).encode("utf-8")

    entries["docProps/thumbnail.jpeg"] = b"\xff\xd8\xff thumbnail"
    root_rels = entries["_rels/.rels"].decode("utf-8").replace(
        "</Relationships>",
        '<Relationship Id="rIdTh" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail" Target="docProps/thumbnail.jpeg"/></Relationships>',
    )
    entries["_rels/.rels"] = root_rels.encode("utf-8")

    if with_chart_and_drawing:
        entries["xl/charts/chart1.xml"] = b"<c:chartSpace xmlns:c='x'/>"
        entries["xl/drawings/drawing1.xml"] = b"<xdr:wsDr xmlns:xdr='x' xmlns:a='y'><a:t>Mario Rossi</a:t></xdr:wsDr>"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name in [*order, *(n for n in entries if n not in order)]:
            target.writestr(name, entries[name])
    path.write_bytes(buffer.getvalue())


def all_xml_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", "ignore") for name in archive.namelist() if not name.endswith("/")
        )
