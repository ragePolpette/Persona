from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas
from typer.testing import CliRunner

from persona import cli
from persona.exceptions import InputError
from persona.documents import open_document
from persona.vault import Argon2Params


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


def test_pdf_through_the_cli_gives_a_txt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PERSONA_PASSWORD", "pw")
    monkeypatch.setattr(Argon2Params.__init__, "__defaults__", (1, 8, 1, 32))
    pdf = make_pdf(tmp_path / "cv.pdf", ["Dott. Mario Rossi", "mario.rossi@example.test"])
    runner = CliRunner()
    assert runner.invoke(cli.app, ["init", "-p", "t"]).exit_code == 0
    result = runner.invoke(cli.app, ["anonymize", str(pdf), "-p", "t"])
    assert result.exit_code == 0, result.output
    anon = (tmp_path / "cv.anon.txt").read_text(encoding="utf-8")
    assert "Rossi" not in anon and "example.test" not in anon
