from __future__ import annotations

from persona.engine import Segment, analyze, anonymize_text, apply, verify
from persona.restore import restore_text
from persona.vault import Vault


def test_a_value_found_once_is_masked_everywhere(vault: Vault) -> None:
    text = "Il Dott. Mario Rossi firma. Poi mario rossi risponde e MARIO ROSSI conferma."
    censored, _ = anonymize_text(text, vault)
    assert "mario rossi" not in censored.lower()
    # Different spellings keep separate placeholders so the restore is exact.
    assert restore_text(censored, vault).text == text


def test_propagation_across_segments(vault: Vault) -> None:
    segments = [Segment("a", "Contatto: Dott. Mario Rossi"), Segment("b", "Nota: Mario Rossi è in ferie")]
    result = apply(analyze(segments, vault), vault)
    assert "Mario Rossi" not in result.texts["a"] + result.texts["b"]
    assert result.texts["a"].endswith("[PERSONA_1]") and "[PERSONA_1]" in result.texts["b"]


def test_bare_surname_and_first_name_follow_a_detected_person(vault: Vault) -> None:
    censored, _ = anonymize_text("Dott. Mario Rossi.\nPoi Rossi ha detto che Mario è stanco.", vault)
    assert "Rossi" not in censored and "Mario" not in censored


def test_aliases_are_case_sensitive_so_common_words_survive(vault: Vault) -> None:
    censored, _ = anonymize_text("Dott. Anna Verdi.\nI colori verdi e le rose rosse.", vault)
    assert "verdi" in censored


def test_vault_values_are_masked_in_later_documents(vault: Vault) -> None:
    anonymize_text("Dott. Mario Rossi lavora per Acme S.r.l.", vault)
    vault.save()
    censored, _ = anonymize_text("Ho sentito Mario Rossi ieri, e Acme S.r.l. conferma.", Vault.open(vault.path, "pw"))
    assert "Mario Rossi" not in censored and "Acme" not in censored
    assert "[PERSONA_1]" in censored and "[AZIENDA_1]" in censored


def test_glossary_catches_what_rules_cannot(vault: Vault) -> None:
    vault.add_glossary("Giulia Marchetti", "PERSONA", ["Giulia"])
    censored, _ = anonymize_text("Ciao Giulia, ne ha parlato Giulia Marchetti.", vault)
    assert "Giulia" not in censored and "Marchetti" not in censored


def test_glossary_matching_ignores_case_and_accents(vault: Vault) -> None:
    vault.add_glossary("Società Perché", "AZIENDA")
    censored, _ = anonymize_text("Contratto con SOCIETA PERCHE e con società perché.", vault)
    assert "perch" not in censored.lower()


def test_glossary_does_not_match_inside_words(vault: Vault) -> None:
    vault.add_glossary("Anna", "PERSONA")
    censored, _ = anonymize_text("Annalisa e Hanna e Anna.", vault)
    assert censored.startswith("Annalisa e Hanna e [PERSONA_1]")


def test_review_can_reject_a_detection(vault: Vault) -> None:
    analysis = analyze([Segment("t", "Scrivere a a@b.example o c@d.example")], vault)
    analysis.spans[0].approved = False
    censored = apply(analysis, vault).texts["t"]
    assert "a@b.example" in censored and "c@d.example" not in censored


def test_verify_flags_what_was_not_masked(vault: Vault) -> None:
    analysis = analyze([Segment("t", "Scrivere a a@b.example")], vault)
    analysis.spans[0].approved = False
    censored = apply(analysis, vault).texts["t"]
    leaks = verify({"t": censored}, vault)
    assert [leak.text for leak in leaks] == ["a@b.example"]


def test_verify_flags_known_values_in_other_text(vault: Vault) -> None:
    anonymize_text("Dott. Mario Rossi", vault)
    assert [leak.text for leak in verify({"x": "Chiamare mario rossi."}, vault)] == ["mario rossi"]


def test_verify_is_quiet_on_clean_output(vault: Vault) -> None:
    censored, _ = anonymize_text("Dott. Mario Rossi, tel. 338 4567890, Acme S.r.l.", vault)
    assert verify({"t": censored}, vault) == []


def test_identical_values_share_one_placeholder_and_restore_exactly(vault: Vault) -> None:
    text = "Dott. Mario Rossi, Mario Rossi, Mario Rossi."
    censored, result = anonymize_text(text, vault)
    assert result.placeholders["[PERSONA_1]"] == 3
    assert restore_text(censored, vault).text == text


def test_names_are_derived_from_email_addresses_and_urls(vault: Vault) -> None:
    text = "Zeno Cosini\nzeno.cosini@example.test\nlinkedin.com/in/zeno-cosini\nPoi COSINI ha scritto."
    censored, _ = anonymize_text(text, vault)
    assert "Cosini" not in censored and "COSINI" not in censored and "Zeno" not in censored
    assert verify({"t": censored}, vault) == []


def test_generic_mailbox_names_are_not_treated_as_people(vault: Vault) -> None:
    censored, _ = anonymize_text("Scrivere a ufficio.acquisti@example.test. Ufficio acquisti risponde.", vault)
    assert "Ufficio acquisti" in censored


def test_adjacent_name_parts_become_one_person(vault: Vault) -> None:
    censored, _ = anonymize_text("Zeno Cosini\nzeno.cosini@example.test", vault)
    assert censored.splitlines()[0] == "[PERSONA_1]"
