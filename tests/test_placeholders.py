from __future__ import annotations

import pytest

from persona.placeholders import find_placeholders


def canon(text: str) -> list[str]:
    return [ref.canonical for ref in find_placeholders(text)]


@pytest.mark.parametrize(
    "written",
    [
        "[PERSONA_1]",
        "[persona_1]",
        "[Persona 1]",
        "[PERSONA-1]",
        "(PERSONA_1)",
        "{PERSONA_1}",
        "<PERSONA_1>",
        r"\[PERSONA\_1\]",
        "**[PERSONA_1]**",
        "PERSONA_1",
    ],
)
def test_tolerates_common_llm_mangling(written: str) -> None:
    assert canon(f"Ciao {written}, come va?") == ["[PERSONA_1]"]


def test_exactness_is_reported() -> None:
    exact, altered = find_placeholders("[AZIENDA_2] e [azienda_2]")
    assert exact.exact and not altered.exact


@pytest.mark.parametrize(
    "text",
    ["[Allegato 1]", "la persona 1 ha detto", "persona_1 minuscolo", "[PERSONAGGIO_1]", "Vedi [1]", "x PERSONA_1abc"],
)
def test_ordinary_text_is_not_a_placeholder(text: str) -> None:
    assert canon(text) == []


def test_multiple_and_adjacent() -> None:
    assert canon("[PERSONA_1][AZIENDA_12] e IBAN_3") == ["[PERSONA_1]", "[AZIENDA_12]", "[IBAN_3]"]


def test_letter_glued_to_bracket_still_matches() -> None:
    assert canon("Sig.[PERSONA_1]x") == ["[PERSONA_1]"]
    assert canon("dell'[AZIENDA_1]") == ["[AZIENDA_1]"]
