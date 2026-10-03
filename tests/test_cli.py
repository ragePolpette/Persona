from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from persona import cli
from persona.vault import Argon2Params

runner = CliRunner()


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERSONA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PERSONA_PASSWORD", "pw")
    # keep Argon2 cheap in tests
    monkeypatch.setattr(Argon2Params.__init__, "__defaults__", (1, 8, 1, 32))


def run(*args: str):
    return runner.invoke(cli.app, list(args))


def test_full_loop(tmp_path: Path) -> None:
    doc = tmp_path / "nota.md"
    doc.write_text("Il Dott. Mario Rossi (Acme S.r.l.) scrive a m.rossi@acme.example.\nPoi Rossi chiama.\n", encoding="utf-8")

    assert run("init", "-p", "acme").exit_code == 0
    dry = run("anonymize", str(doc), "-p", "acme", "--dry-run")
    assert dry.exit_code == 0 and "Mario Rossi" in dry.output
    assert not (tmp_path / "nota.anon.md").exists()

    done = run("anonymize", str(doc), "-p", "acme")
    assert done.exit_code == 0, done.output
    anon = (tmp_path / "nota.anon.md").read_text(encoding="utf-8")
    assert "Rossi" not in anon and "Acme" not in anon and "[PERSONA_1]" in anon

    assert run("verify", str(tmp_path / "nota.anon.md"), "-p", "acme").exit_code == 0

    ai = tmp_path / "ai.md"
    ai.write_text(anon.replace("[PERSONA_1]", "**[persona_1]**") + "\nGrazie [PERSONA_9]\n", encoding="utf-8")
    restored = run("restore", str(ai), "--sent", str(tmp_path / "nota.anon.md"), "-p", "acme")
    assert restored.exit_code == 3  # invented placeholder -> non-zero, but still written
    text = (tmp_path / "ai.restored.md").read_text(encoding="utf-8")
    assert "**Mario Rossi**" in text and "Acme S.r.l." in text and "[PERSONA_9]" in text
    assert "[PERSONA_9]" in restored.output


def test_safety_check_blocks_output_when_something_is_left(tmp_path: Path, monkeypatch) -> None:
    from persona import engine

    doc = tmp_path / "a.txt"
    doc.write_text("Scrivere a a@b.example", encoding="utf-8")
    run("init", "-p", "x")
    real_apply = engine.apply

    def leaky_apply(analysis, vault):
        for span in analysis.spans:
            span.approved = False
        return real_apply(analysis, vault)

    monkeypatch.setattr(cli, "apply", leaky_apply)
    result = run("anonymize", str(doc), "-p", "x")
    assert result.exit_code == 2
    assert not (tmp_path / "a.anon.txt").exists()
    forced = run("anonymize", str(doc), "-p", "x", "--force")
    assert forced.exit_code == 0 and (tmp_path / "a.anon.txt").exists()


def test_glossary_via_cli(tmp_path: Path) -> None:
    doc = tmp_path / "a.txt"
    doc.write_text("Ne parla Giulia Marchetti con Cooperativa Il Girasole.", encoding="utf-8")
    run("init", "-p", "g")
    assert run("glossary", "add", "Giulia Marchetti", "-k", "PERSONA", "-a", "Giulia", "-p", "g").exit_code == 0
    assert run("glossary", "add", "Cooperativa Il Girasole", "-k", "AZIENDA", "-p", "g").exit_code == 0
    assert "Giulia Marchetti" in run("glossary", "list", "-p", "g").output
    assert run("anonymize", str(doc), "-p", "g").exit_code == 0
    anon = (tmp_path / "a.anon.txt").read_text(encoding="utf-8")
    assert "Giulia" not in anon and "Girasole" not in anon


def test_clean_errors(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    run("init", "-p", "e")
    unsupported = run("anonymize", str(pdf), "-p", "e")
    assert unsupported.exit_code == 1 and "Unsupported file type" in unsupported.output
    assert run("anonymize", str(pdf)).exit_code == 1  # no project
    missing = run("init", "-p", "e")  # already exists
    assert missing.exit_code == 1 and "already exists" in missing.output
