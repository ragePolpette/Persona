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


def test_known_first_name_plus_surname_without_title() -> None:
    assert ("PERSONA", "Giulia Marchetti") in found("Ne ha parlato Giulia Marchetti con Roberto.")
    assert ("PERSONA", "Maria Chiara De Luca") in found("Firmato Maria Chiara De Luca ieri")
    assert ("PERSONA", "Mario Rossi") in found("Mario Rossi Luca Bianchi")
    assert ("PERSONA", "Luca Bianchi") in found("Mario Rossi Luca Bianchi")


def test_names_not_in_the_first_name_list_or_alone_are_a_known_gap() -> None:
    # Documented limitation: this is what the glossary exists for.
    assert [k for k, _ in found("Ne ha parlato Giulia con Roberto.")] == []
    assert [k for k, _ in found("Ne ha parlato Zeno Cosini.")] == []
    assert [k for k, _ in found("Progetto Aurora e la rosa rossa")] == []


def test_labeled_names_on_forms() -> None:
    assert ("PERSONA", "Chiara") in found("Nome: Chiara\nCognome: De Luca")
    assert ("PERSONA", "De Luca") in found("Nome: Chiara\nCognome: De Luca")
    assert ("PERSONA", "Giulia Marchetti") in found("Referente: Dott.ssa Giulia Marchetti, tel.")


def test_labeled_name_does_not_swallow_a_title_left_before_a_placeholder() -> None:
    assert found("Referente: Dott.ssa [PERSONA_2], tel.") == []


@pytest.mark.parametrize(
    "url",
    ["linkedin.com/in/mario-rossi", "github.com/zeno-dev", "https://www.acme.example/chi-siamo", "www.acme.example"],
)
def test_urls(url: str) -> None:
    assert ("URL", url) in found(f"Profilo: {url}.")


def test_technology_names_and_filenames_are_not_urls() -> None:
    assert [k for k, _ in found("Stack: Node.js, Vue.js, ASP.NET, report.xlsx, e.g. SQL")] == []


def test_via_followed_by_an_acronym_is_not_an_address() -> None:
    assert found("Ho integrato via API e via MCP con il server") == []


def test_institutions_without_a_legal_suffix() -> None:
    assert ("AZIENDA", "Liceo Scientifico Esedra") in found("Diploma: Liceo Scientifico Esedra – Lucca")
    assert ("AZIENDA", "Cooperativa Il Girasole") in found("ritardi su Cooperativa Il Girasole, il nostro")
    assert ("AZIENDA", "Studio Legale Caruso & Associati") in found("Studio Legale Caruso & Associati\nVia")
    assert [k for k, _ in found("Ho fatto uno studio sulla scuola")] == []


@pytest.mark.parametrize(
    "phone", ["+44 20 7946 0958", "+49 711 1234567", "+34 91 123 45 67", "+1 415 555 0132", "+33 1 42 68 53 00"]
)
def test_international_phone_numbers(phone: str) -> None:
    assert ("TELEFONO", phone) in found(f"chiamare {phone} domani")


@pytest.mark.parametrize("text", ["crescita +3.5% annua", "+12 mesi", "tel. +IVA", "+2026 punti"])
def test_plus_signs_in_ordinary_text_are_not_phones(text: str) -> None:
    assert [k for k, _ in found(text) if k == "TELEFONO"] == []


@pytest.mark.parametrize("vat", ["DE123456789", "ESB12345674", "ATU12345678", "FR12345678901", "NL123456789B01"])
def test_eu_vat_numbers(vat: str) -> None:
    assert ("PIVA", vat) in found(f"Partita {vat} intestata")


def test_labeled_vat_with_other_formats() -> None:
    assert ("PIVA", "CHE123456789") in found("VAT: CHE123456789")
    assert ("PIVA", "B12345678") not in found("sede B12345678")


def test_foreign_ibans() -> None:
    assert ("IBAN", "GB29 NWBK 6016 1331 9268 19") in found("IBAN GB29 NWBK 6016 1331 9268 19.")
    assert ("IBAN", "ES91 2100 0418 4502 0005 1332") in found("IBAN: ES91 2100 0418 4502 0005 1332")


@pytest.mark.parametrize(
    "address",
    [
        "221B Baker Street, London NW1 6XE",
        "14 King's Road, Brighton BN1 2PQ",
        "Königsstraße 12, 70173 Stuttgart",
        "Hauptstrasse 5, 10115 Berlin",
        "Calle Mayor 25, 28013 Madrid",
        "Avenida de la Constitución 3, 41004 Sevilla",
        "12 rue de la Paix, 75002 Paris",
        "Via XX Settembre 18",
    ],
)
def test_foreign_and_roman_numeral_addresses(address: str) -> None:
    assert ("INDIRIZZO", address) in found(f"sede in {address}.")


def test_dates_and_numbers_before_street_words_are_not_addresses() -> None:
    assert [k for k, _ in found("entro 30 days from now, 2 Way trips")] == []


def test_birth_date_plate_and_id_document_by_label() -> None:
    text = (
        "nato a Salerno (SA) il 12/03/1980, targa AB123CD, documento di identità n. CA12345AB; "
        "Data di nascita: 01.02.1975"
    )
    assert ("ALTRO", "12/03/1980") in found(text)
    assert ("ALTRO", "AB123CD") in found(text)
    assert ("ALTRO", "CA12345AB") in found(text)
    assert ("ALTRO", "01.02.1975") in found(text)


def test_unlabeled_dates_and_plates_are_left_alone() -> None:
    assert found("Salerno, 02/04/2026. Codice AB123CD. Fattura del 10/03/2026.") == []


def test_english_titles_and_first_names() -> None:
    assert ("PERSONA", "Emily Carter") in found("Signed by Mrs. Emily Carter, Managing Director")
    assert ("PERSONA", "Smith") in found("Mr. Smith agreed")
    assert ("PERSONA", "John Peterson") in found("between John Peterson and the Client")


def test_foreign_company_suffixes() -> None:
    assert ("AZIENDA", "Müller Maschinenbau GmbH") in found("Lieferant: Müller Maschinenbau GmbH, Stuttgart")
    assert ("AZIENDA", "Ibérica Suministros S.L.") in found("Cliente: Ibérica Suministros S.L., Madrid")
    assert ("AZIENDA", "Northwind Trading Ltd") in found("between Northwind Trading Ltd, registered")
    assert ("AZIENDA", "Delta Soluciones SARL") in found("avec Delta Soluciones SARL à Lyon")


def test_ambiguous_english_words_are_not_names() -> None:
    assert found("Grace Period applies. Mark Up and Will Call. Frank Offer, Rose Garden.") == []
