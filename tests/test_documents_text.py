from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas
from typer.testing import CliRunner

from persona import cli
from persona.documents import open_document
from persona.exceptions import InputError


def make_pdf(path: Path, lines: list[str]) -> Path:
    pdf = canvas.Canvas(str(path))
    y = 800
    for line in lines:
        pdf.drawString(40, y, line)
        y -= 16
    pdf.save()
    return path


def test_pdf_text_is_extracted(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "cv.pdf", ["Dott. Mario Rossi", "mario.rossi@example.test"])
    document = open_document(pdf)
    text = document.segments[0].text
    assert document.output_suffix == ".txt"
    assert "Dott. Mario Rossi" in text and "mario.rossi@example.test" in text


def test_pdf_without_text_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "scan.pdf"
    pdf = canvas.Canvas(str(empty))
    pdf.showPage()
    pdf.save()
    with pytest.raises(InputError, match="OCR"):
        open_document(empty)


def test_broken_pdf_is_a_clean_error(tmp_path: Path) -> None:
    broken = tmp_path / "x.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(InputError):
        open_document(broken)


def test_pdf_through_the_cli_gives_a_txt(tmp_path: Path, cli_env: Path) -> None:
    pdf = make_pdf(tmp_path / "cv.pdf", ["Dott. Mario Rossi", "mario.rossi@example.test"])
    runner = CliRunner()
    assert runner.invoke(cli.app, ["init", "-p", "t"]).exit_code == 0
    result = runner.invoke(cli.app, ["anonymize", str(pdf), "-p", "t"])
    assert result.exit_code == 0, result.output
    anon = (tmp_path / "cv.anon.txt").read_text(encoding="utf-8")
    assert "Rossi" not in anon and "example.test" not in anon


def _anonymize_cli(path: Path) -> CliRunner:
    runner = CliRunner()
    assert runner.invoke(cli.app, ["init", "-p", "enc"]).exit_code == 0
    result = runner.invoke(cli.app, ["anonymize", str(path), "-p", "enc"])
    assert result.exit_code == 0, result.output
    return runner


def test_windows_line_endings_are_preserved(tmp_path: Path, cli_env: Path) -> None:
    source = tmp_path / "nota.txt"
    source.write_bytes(b"Dott. Mario Rossi\r\nTel. 338 4567890\r\nfine\n")
    _anonymize_cli(source)
    assert (tmp_path / "nota.anon.txt").read_bytes() == b"Dott. [PERSONA_1]\r\nTel. [TELEFONO_1]\r\nfine\n"


def test_utf8_bom_is_not_part_of_the_text_and_is_written_back(tmp_path: Path, cli_env: Path) -> None:
    source = tmp_path / "nota.md"
    source.write_bytes("﻿Mario Rossi è qui".encode())
    assert open_document(source).segments[0].text == "Mario Rossi è qui"
    _anonymize_cli(source)
    assert (tmp_path / "nota.anon.md").read_bytes() == "﻿[PERSONA_1] è qui".encode()


def test_windows_1252_files_are_read(tmp_path: Path, cli_env: Path) -> None:
    source = tmp_path / "vecchio.txt"
    source.write_bytes("Il Dott. Mario Rossi è già qui, perché sì.".encode("cp1252"))
    assert open_document(source).segments[0].text == "Il Dott. Mario Rossi è già qui, perché sì."
    _anonymize_cli(source)
    assert (tmp_path / "vecchio.anon.txt").read_text(encoding="utf-8") == "Il Dott. [PERSONA_1] è già qui, perché sì."


def test_undecodable_text_is_a_clean_error(tmp_path: Path) -> None:
    source = tmp_path / "x.txt"
    source.write_bytes(b"\x81\x8d\x8f\x90\x9d")
    with pytest.raises(InputError, match="encoding"):
        open_document(source)
