from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from persona import cli
from persona.restore import placeholders_in
from persona.vault import Vault

runner = CliRunner()


@pytest.fixture(autouse=True)
def env(cli_env: Path) -> None:
    pass


def run(*args: str):
    return runner.invoke(cli.app, list(args))


def run_with_input(text: str, *args: str):
    return runner.invoke(cli.app, list(args), input=text.encode("utf-8"))


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
    docx = tmp_path / "a.doc"
    docx.write_bytes(b"PK")
    run("init", "-p", "e")
    unsupported = run("anonymize", str(docx), "-p", "e")
    assert unsupported.exit_code == 1 and "Unsupported file type" in unsupported.output
    assert run("anonymize", str(docx)).exit_code == 1  # no project
    missing = run("init", "-p", "e")  # already exists
    assert missing.exit_code == 1 and "already exists" in missing.output


def test_the_mapping_is_saved_before_the_anonymized_file_appears(tmp_path: Path, monkeypatch) -> None:
    doc = tmp_path / "a.txt"
    doc.write_text("Il Dott. Mario Rossi scrive a m.rossi@acme.example", encoding="utf-8")
    run("init", "-p", "m")

    def crash(self, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Vault, "save", crash)
    result = run("anonymize", str(doc), "-p", "m")
    assert result.exit_code != 0
    assert not (tmp_path / "a.anon.txt").exists()  # no anonymized file whose mapping was never stored
    assert not list(tmp_path.glob(".*staging*"))


def test_every_placeholder_written_is_in_the_saved_vault(tmp_path: Path, cli_env: Path) -> None:
    doc = tmp_path / "a.txt"
    doc.write_text("Il Dott. Mario Rossi scrive a m.rossi@acme.example", encoding="utf-8")
    run("init", "-p", "m")
    assert run("anonymize", str(doc), "-p", "m").exit_code == 0
    saved = Vault.open(cli_env / "projects" / "m.vault", "pw")
    for placeholder in placeholders_in((tmp_path / "a.anon.txt").read_text(encoding="utf-8")):
        kind, number = placeholder.strip("[]").rsplit("_", 1)
        assert saved.lookup(kind, int(number)) is not None


def test_review_with_dry_run_warns_that_it_is_ignored(tmp_path: Path) -> None:
    doc = tmp_path / "a.txt"
    doc.write_text("Scrivere a a@b.example", encoding="utf-8")
    run("init", "-p", "w")
    result = run("anonymize", str(doc), "-p", "w", "--dry-run", "--review")
    assert result.exit_code == 0
    assert "--review is ignored with --dry-run" in result.output


def test_rekey_via_cli(tmp_path: Path, cli_env: Path, monkeypatch) -> None:
    run("init", "-p", "k")
    run("glossary", "add", "Zeno Cosini", "-k", "PERSONA", "-p", "k")
    monkeypatch.setenv("PERSONA_NEW_PASSWORD", "new-pw")
    result = run("rekey", "-p", "k")
    assert result.exit_code == 0, result.output
    assert "backup" in result.output
    assert run("glossary", "list", "-p", "k").exit_code == 1  # old password no longer works
    monkeypatch.setenv("PERSONA_PASSWORD", "new-pw")
    assert "Zeno Cosini" in run("glossary", "list", "-p", "k").output


def _tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("Il Dott. Mario Rossi scrive a m.rossi@acme.example", encoding="utf-8")
    (root / "b.md").write_text("Chiamare il 338 4567890", encoding="utf-8")
    (root / "old.anon.txt").write_text("[PERSONA_1]", encoding="utf-8")
    (root / "notes.doc").write_bytes(b"PK")
    (root / "sub" / "c.txt").write_text("Fornitore: Acme S.r.l.", encoding="utf-8")


def test_batch_directory_with_json_report(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    _tree(root)
    run("init", "-p", "b")
    result = run("anonymize", str(root), "-p", "b", "--json")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    statuses = {Path(item["source"]).name: item["status"] for item in report["files"]}
    assert statuses == {"a.txt": "written", "b.md": "written", "notes.doc": "skipped"}
    assert report["summary"]["written"] == 2
    assert "Mario" not in result.stdout and "338" not in result.stdout  # counts only, never values
    assert (root / "a.anon.txt").exists() and not (root / "old.anon.anon.txt").exists()
    assert not (root / "sub" / "c.anon.txt").exists()

    recursive = run("anonymize", str(root), "-p", "b", "--recursive", "--out", str(tmp_path / "out"))
    assert recursive.exit_code == 0, recursive.output
    assert "Acme" not in (tmp_path / "out" / "sub" / "c.anon.txt").read_text(encoding="utf-8")
    assert (tmp_path / "out" / "a.anon.txt").exists()


def test_batch_reports_blocked_files_and_keeps_going(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "docs"
    _tree(root)
    run("init", "-p", "b")
    real_apply = cli.apply

    def leaky_apply(analysis, vault):
        for span in analysis.spans:
            span.approved = "Rossi" not in span.text
        return real_apply(analysis, vault)

    monkeypatch.setattr(cli, "apply", leaky_apply)
    result = run("anonymize", str(root), "-p", "b", "--json")
    assert result.exit_code == 2
    statuses = {Path(item["source"]).name: item["status"] for item in json.loads(result.stdout)["files"]}
    assert statuses["a.txt"] == "blocked" and statuses["b.md"] == "written"
    assert not (root / "a.anon.txt").exists()


def test_stdin_to_stdout(tmp_path: Path, cli_env: Path) -> None:
    run("init", "-p", "s")
    result = run_with_input("Il Dott. Mario Rossi, tel. 338 4567890\n", "anonymize", "--stdin", "-p", "s")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Il Dott. [PERSONA_1], tel. [TELEFONO_1]\n"
    assert Vault.open(cli_env / "projects" / "s.vault", "pw").lookup("PERSONA", 1).value == "Mario Rossi"


def test_text_file_to_stdout_and_its_limits(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text("Scrivere a a@b.example", encoding="utf-8")
    run("init", "-p", "s")
    result = run("anonymize", str(doc), "-p", "s", "--stdout")
    assert result.exit_code == 0 and result.stdout == "Scrivere a [EMAIL_1]"
    assert not (tmp_path / "a.anon.md").exists()
    assert run("anonymize", str(tmp_path), "-p", "s", "--stdout").exit_code == 1
    assert run("anonymize", "--stdin", "-p", "s", "--review").exit_code == 1
    assert run("anonymize", "-p", "s").exit_code == 1  # neither a path nor --stdin
