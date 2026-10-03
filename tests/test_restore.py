from __future__ import annotations

from persona.engine import anonymize_text
from persona.restore import placeholders_in, restore_text
from persona.vault import Vault

ORIGINAL = "Dott. Mario Rossi (Acme S.r.l.) scrive a m.rossi@acme.example, tel. 338 4567890."


def setup(vault: Vault) -> str:
    censored, _ = anonymize_text(ORIGINAL, vault)
    return censored


def test_identity_roundtrip(vault: Vault) -> None:
    censored = setup(vault)
    report = restore_text(censored, vault, expected=placeholders_in(censored))
    assert report.text == ORIGINAL
    assert report.clean and not report.altered


def test_markdown_escaped_and_recased_placeholders(vault: Vault) -> None:
    censored = setup(vault)
    mangled = censored.replace("_", r"\_").replace("[PERSONA", "[persona")
    report = restore_text(mangled, vault)
    assert report.text == ORIGINAL
    assert len(report.altered) >= 2


def test_ai_that_rewrites_around_placeholders(vault: Vault) -> None:
    censored = setup(vault)
    ai_output = "Gentile **[PERSONA_1]**,\n\nla ringraziamo da parte di [AZIENDA_1]. Risponda a (EMAIL_1) o al TELEFONO_1."
    report = restore_text(ai_output, vault)
    assert "**Mario Rossi**" in report.text
    assert "Acme S.r.l." in report.text and "m.rossi@acme.example" in report.text and "338 4567890" in report.text
    assert len(report.altered) == 2  # (EMAIL_1) and bare TELEFONO_1


def test_placeholders_invented_by_the_ai_are_reported_and_left_alone(vault: Vault) -> None:
    setup(vault)
    report = restore_text("Scrivere a [PERSONA_1] e a [PERSONA_9].", vault)
    assert report.text == "Scrivere a Mario Rossi e a [PERSONA_9]."
    assert report.invented == ["[PERSONA_9]"] and not report.clean


def test_dropped_placeholders_are_reported(vault: Vault) -> None:
    censored = setup(vault)
    report = restore_text("Solo [PERSONA_1] qui.", vault, expected=placeholders_in(censored))
    assert "[AZIENDA_1]" in report.missing and "[EMAIL_1]" in report.missing
    assert "[PERSONA_1]" not in report.missing and not report.clean


def test_ordinary_brackets_are_untouched(vault: Vault) -> None:
    setup(vault)
    text = "Vedi [Allegato 1] e [1] e la persona 1."
    assert restore_text(text, vault).text == text


def test_possessive_and_plural_suffixes(vault: Vault) -> None:
    setup(vault)
    assert restore_text("l'email di [PERSONA_1]'s team", vault).text == "l'email di Mario Rossi's team"
