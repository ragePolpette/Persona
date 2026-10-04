from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from persona import cli
from persona.engine import Segment, analyze, anonymize_text, apply, verify
from persona.review import group_spans, run_review
from persona.vault import Argon2Params, Vault

TEXT = "Mandare a mario.rossi@example.test o a info@acme.example. Il progetto Aurora Borealis parte domani."


class Script:
    """Scripted answers; records the prompts so tests can assert on what was asked."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.said: list[str] = []

    def ask(self, prompt: str, default: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else default

    def say(self, text: str) -> None:
        self.said.append(text)


def segments(text: str = TEXT) -> list[Segment]:
    return [Segment("t", text)]


def test_groups_show_context_and_count(vault: Vault) -> None:
    analysis = analyze(segments("a@b.example e ancora a@b.example, poi Aurora Borealis."), vault)
    group = next(g for g in group_spans(analysis) if g.text == "a@b.example")
    assert group.count == 2 and group.kind == "EMAIL"
    assert group.contexts[0].count("«a@b.example»") == 1


def test_skip_never_and_mask(vault: Vault) -> None:
    script = Script("m", "s", "n", "")  # groups come as: info@ (EMAIL), mario.rossi@ (EMAIL), Aurora Borealis (PERSONA)
    analysis = run_review(lambda: analyze(segments(), vault), vault, script.ask, script.say)
    by_text = {span.text: span.approved for span in analysis.spans}
    assert by_text == {"info@acme.example": True, "mario.rossi@example.test": False, "Aurora Borealis": False}
    assert vault.allowlist == ["Aurora Borealis"]  # only the "never" answer is remembered
    assert "info@acme.example" in script.said[0]


def test_all_the_rest_stops_asking(vault: Vault) -> None:
    script = Script("a", "")
    run_review(lambda: analyze(segments(), vault), vault, script.ask, script.say)
    questions = [p for p in script.prompts if p.startswith("[m]ask")]
    assert len(questions) == 1


def test_invalid_answers_are_asked_again(vault: Vault) -> None:
    script = Script("zzz", "x", "m", "m", "m", "")
    run_review(lambda: analyze(segments(), vault), vault, script.ask, script.say)
    assert sum(p.startswith("[m]ask") for p in script.prompts) == 5


def test_missed_names_are_added_to_the_glossary_and_reviewed(vault: Vault) -> None:
    text = "Parla con Zeno Cosini domani. Scrivi a a@b.example."
    script = Script("m", "Zeno Cosini", "persona", "m", "")  # mask email; add a name; mask it; done
    analysis = run_review(lambda: analyze(segments(text), vault), vault, script.ask, script.say)
    assert [g.term for g in vault.glossary] == ["Zeno Cosini"] and vault.glossary[0].kind == "PERSONA"
    assert {span.text for span in analysis.spans if span.approved} == {"a@b.example", "Zeno Cosini"}


def test_bad_kind_is_asked_again(vault: Vault) -> None:
    script = Script("a", "Zeno Cosini", "robot", "azienda", "")
    run_review(lambda: analyze(segments("Zeno Cosini"), vault), vault, script.ask, script.say)
    assert vault.glossary[0].kind == "AZIENDA"
    assert any("Unknown kind" in line for line in script.said)


# -- allowlist ------------------------------------------------------------------------------


def test_allowlisted_values_are_never_masked_anywhere(vault: Vault) -> None:
    vault.allow("Aurora Borealis")
    censored, _ = anonymize_text("Aurora Borealis qui. E ancora aurora borealis, non Mario Bianchi.", vault)
    assert "Aurora Borealis" in censored and "aurora borealis" in censored
    assert "Mario Bianchi" not in censored


def test_allowlist_beats_known_values_from_the_vault(vault: Vault) -> None:
    anonymize_text("Dott. Mario Rossi", vault)
    vault.allow("Mario Rossi")
    censored, _ = anonymize_text("Ha scritto Mario Rossi.", vault)
    assert "Mario Rossi" in censored


def test_verify_does_not_flag_allowlisted_values(vault: Vault) -> None:
    vault.allow("info@acme.example")
    assert verify({"t": "Scrivere a info@acme.example"}, vault) == []


def test_allowlist_is_case_and_accent_insensitive_and_persisted(vault: Vault) -> None:
    vault.allow("Società Perché")
    vault.save()
    reopened = Vault.open(vault.path, "pw")
    assert reopened.is_allowed("SOCIETA PERCHE") and not reopened.is_allowed("Società")
    assert reopened.disallow("società perché") and reopened.allowlist == []
    assert not reopened.disallow("nope")


def test_old_vaults_without_an_allowlist_still_open(vault: Vault) -> None:
    vault.save()
    assert Vault.open(vault.path, "pw").allowlist == []


def test_glossary_remove(vault: Vault) -> None:
    vault.add_glossary("Acme", "AZIENDA")
    assert vault.remove_glossary("Acme") and not vault.remove_glossary("Acme")


# -- CLI --------------------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PERSONA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PERSONA_PASSWORD", "pw")
    monkeypatch.setattr(Argon2Params.__init__, "__defaults__", (1, 8, 1, 32))
    assert CliRunner().invoke(cli.app, ["init", "-p", "r"]).exit_code == 0
    return tmp_path


def test_cli_review_flow(project: Path) -> None:
    doc = project / "n.txt"
    doc.write_text(TEXT, encoding="utf-8")
    runner = CliRunner()
    # groups: info@ (skip), mario.rossi@ (mask), Aurora Borealis (never); nothing missed
    result = runner.invoke(cli.app, ["anonymize", str(doc), "-p", "r", "--review"], input="s\nm\nn\n\n")
    assert result.exit_code == 0, result.output  # skipped values are the user's choice: no "leak" alarm
    anon = (project / "n.anon.txt").read_text(encoding="utf-8")
    assert "Aurora Borealis" in anon and "info@acme.example" in anon and "mario.rossi" not in anon
    assert "Aurora Borealis" in runner.invoke(cli.app, ["allow", "list", "-p", "r"]).output
    # the next run needs no review: the false positive is remembered
    again = runner.invoke(cli.app, ["anonymize", str(doc), "-p", "r", "--dry-run"])
    assert "Aurora" not in again.output


def test_cli_exclude_is_this_time_only(project: Path) -> None:
    doc = project / "n.txt"
    doc.write_text("Scrivi a a@b.example e c@d.example", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(cli.app, ["anonymize", str(doc), "-p", "r", "-x", "a@b.example"]).exit_code == 0
    anon = (project / "n.anon.txt").read_text(encoding="utf-8")
    assert "a@b.example" in anon and "c@d.example" not in anon
    assert runner.invoke(cli.app, ["allow", "list", "-p", "r"]).output.strip() == ""


def test_cli_allow_and_glossary_management(project: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(cli.app, ["allow", "add", "Aurora Borealis", "-p", "r"]).exit_code == 0
    assert runner.invoke(cli.app, ["allow", "remove", "Aurora Borealis", "-p", "r"]).exit_code == 0
    missing = runner.invoke(cli.app, ["allow", "remove", "Aurora Borealis", "-p", "r"])
    assert missing.exit_code == 1 and "not in the allowlist" in missing.output
    runner.invoke(cli.app, ["glossary", "add", "Acme", "-k", "AZIENDA", "-p", "r"])
    assert runner.invoke(cli.app, ["glossary", "remove", "Acme", "-p", "r"]).exit_code == 0
    assert runner.invoke(cli.app, ["glossary", "remove", "Acme", "-p", "r"]).exit_code == 1


def test_verify_accepts_values_the_user_chose_to_leave_in(vault: Vault) -> None:
    assert [leak.text for leak in verify({"t": "Scrivi a a@b.example"}, vault)] == ["a@b.example"]
    assert verify({"t": "Scrivi a a@b.example"}, vault, accepted=["A@B.example"]) == []
