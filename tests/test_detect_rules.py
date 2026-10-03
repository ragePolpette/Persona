from __future__ import annotations

import pytest

from persona.detect import RuleDetector
from persona.detect.validators import (
    cf_check_char,
    iban_check_digits,
    is_valid_cf,
    is_valid_iban,
    is_valid_piva,
    piva_check_digit,
)

detector = RuleDetector()


def found(text: str) -> list[tuple[str, str]]:
    return [(s.kind, s.text) for s in sorted(detector.detect(text), key=lambda s: s.start)]


def test_validators_accept_known_good_values_and_reject_typos() -> None:
    assert is_valid_cf("RSSMRA80A01H501U")
    assert not is_valid_cf("RSSMRA80A01H501X")
    assert is_valid_iban("IT60X0542811101000000123456")
    assert not is_valid_iban("IT61X0542811101000000123456")
    assert is_valid_piva("12345678903")
    assert not is_valid_piva("12345678904")


def test_generators_agree_with_validators() -> None:
    assert is_valid_cf("MRCGLI85M41D612" + cf_check_char("MRCGLI85M41D612"))
    assert is_valid_piva("0412345678" + str(piva_check_digit("0412345678")))
    assert is_valid_iban("IT" + iban_check_digits("IT", "X0306909606100000063456") + "X0306909606100000063456")


def test_structured_identifiers() -> None:
    text = (
        "CF RSSMRA80A01H501U, mail m.rossi@acme.example, "
        "IBAN IT60 X054 2811 1010 0000 0123 456 e P.IVA 12345678903."
    )
    assert ("CF", "RSSMRA80A01H501U") in found(text)
    assert ("EMAIL", "m.rossi@acme.example") in found(text)
    assert ("IBAN", "IT60 X054 2811 1010 0000 0123 456") in found(text)
    assert ("PIVA", "12345678903") in found(text)


def test_labeled_ids_are_masked_even_with_a_bad_checksum() -> None:
    assert ("CF", "RSSMRA80A01H501X") in found("C.F. RSSMRA80A01H501X")
    assert ("PIVA", "12345678904") in found("Partita IVA: 12345678904")


def test_unlabeled_invalid_numbers_are_left_alone() -> None:
    assert not any(kind in {"PIVA", "CF", "IBAN"} for kind, _ in found("ordine 12345678904 e IT61X0542811101000000123456"))


@pytest.mark.parametrize(
    "phone", ["+39 055 1234567", "338 4567890", "02 7654321", "0039 333 1112233", "081 5551234", "349-8765432"]
)
def test_italian_phone_numbers(phone: str) -> None:
    assert ("TELEFONO", phone) in found(f"chiamare il {phone} domani")


@pytest.mark.parametrize("text", ["€ 300.000.000", "03.01.2026", "01/03/2026", "ordine 2026/0457", "4.500 metri", "18%"])
def test_amounts_dates_and_numbers_are_not_phones(text: str) -> None:
    assert [k for k, _ in found(text) if k == "TELEFONO"] == []


def test_people_with_titles() -> None:
    assert ("PERSONA", "Mario Rossi") in found("Il Dott. Mario Rossi ha firmato.")
    assert ("PERSONA", "Elena Sorrentino") in found("Avv. Elena Sorrentino\nVia Roma")
    assert ("PERSONA", "Chiara De Luca") in found("Sig.ra Chiara De Luca, nata a Napoli")
    assert [k for k, _ in found("Il dottore ha firmato.")] == []


def test_title_name_stops_before_following_words() -> None:
    assert ("PERSONA", "Marco Verdi") in found("Avv. Marco Verdi Via Roma 3")


def test_companies() -> None:
    assert ("AZIENDA", "Tessitura Valdarno S.r.l.") in found("Spett.le Tessitura Valdarno S.r.l., buongiorno")
    assert ("AZIENDA", "Acme S.p.A.") in found("Il contratto tra Acme S.p.A. e Beta S.n.c. è firmato")
    assert ("AZIENDA", "Beta S.n.c.") in found("Il contratto tra Acme S.p.A. e Beta S.n.c. è firmato")
    assert ("AZIENDA", "Rossi & Figli S.n.c.") in found("da Rossi & Figli S.n.c.")


def test_lowercase_sa_is_not_a_company_suffix() -> None:
    assert [k for k, _ in found("Mario sa che Luigi sa")] == []


def test_addresses() -> None:
    assert ("INDIRIZZO", "Via Giuseppe Mazzini 14, 50123 Firenze (FI)") in found(
        "sede in Via Giuseppe Mazzini 14, 50123 Firenze (FI), P.IVA"
    )
    assert ("INDIRIZZO", "Via dei Mille 3/B, 80121 Napoli") in found("Residenza: Via dei Mille 3/B, 80121 Napoli")
    assert ("INDIRIZZO", "Piazza della Repubblica 5, 10121 Torino") in found("Piazza della Repubblica 5, 10121 Torino")
    assert [k for k, _ in found("ti scrivo via email")] == []


def test_known_gap_names_without_title_are_not_detected() -> None:
    # Documented limitation: this is what the glossary exists for.
    assert [k for k, _ in found("Ne ha parlato Giulia Marchetti con Roberto.")] == []
