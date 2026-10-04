"""Deterministic detectors for Italian business documents.

Structured identifiers are validated by checksum (high confidence). Names, companies and
addresses are heuristics with real gaps: a name with no title and no glossary entry is
NOT caught here. That is what the glossary (and later a NER/LLM layer) is for.
"""

from __future__ import annotations

import re
from typing import Iterator

from persona.detect.base import (
    PRIORITY_HEURISTIC,
    PRIORITY_PATTERN,
    PRIORITY_VALIDATED,
    Span,
)
from persona.detect.names import is_first_name
from persona.detect.validators import IBAN_LENGTHS, is_valid_cf, is_valid_iban, is_valid_piva

_UP = "A-ZÀ-ÖØ-Þ"
_LOW = "a-zà-öø-ÿ"

# --- structured identifiers ------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")

_IBAN_START = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2})(\d{2})(?=[ A-Za-z0-9])")

_CF_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]{6}[\dLMNPQRSTUVlmnpqrstuv]{2}[A-Za-z][\dLMNPQRSTUVlmnpqrstuv]{2}"
    r"[A-Za-z][\dLMNPQRSTUVlmnpqrstuv]{3}[A-Za-z](?![A-Za-z0-9])"
)
_CF_LABELED = re.compile(
    r"(?:\bC\.?\s?F\.?|Codice\s+Fiscale)\s*[:.]?\s*([A-Za-z0-9]{16})(?![A-Za-z0-9])", re.IGNORECASE
)

_PIVA_PATTERN = re.compile(r"(?<![\w.,])(?:IT)?(\d{11})(?![\w])")
_PIVA_LABELED = re.compile(
    r"(?:P\.?\s?IVA|Partita\s+IVA|VAT)\s*[:.]?\s*((?:IT)?\d{11})(?!\d)", re.IGNORECASE
)

_PHONE = re.compile(
    r"(?<![\w.,/+\-])(?:(?:\+|00)39[ .\-]?)?"
    r"(?:3\d{2}(?:[ .\-]?\d){6,7}|0\d{1,3}(?:[ .\-]?\d){5,8})(?![\w])"
)

_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")

# --- names, companies, addresses ----------------------------------------------------

_PARTICLE = r"(?:(?:de|di|da|del|della|lo|la|van|von)[ \t]+|d['’])"
_NAME_WORD = rf"{_PARTICLE}?[{_UP}][{_UP}{_LOW}'’\-]+"
_TITLE = (
    r"(?i:Sig\.ra|Sig\.na|Sig\.|Signora|Signor|Signore|Dott\.ssa|Dott\.|Dr\.ssa|Dr\.|Avv\.|"
    r"Ing\.|Prof\.ssa|Prof\.|Geom\.|Arch\.|Rag\.|Notaio)"
)
_PERSON_WITH_TITLE = re.compile(
    rf"(?<![\w]){_TITLE}[ \t]+(?P<name>{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
)
_CAPITALISED_CHAINS = re.compile(
    rf"(?<![\w])[{_UP}][{_UP}{_LOW}'’\-]+(?:[ \t]+(?:(?:de|di|da|del|della|lo|la|van|von)[ \t]+)?[{_UP}][{_UP}{_LOW}'’\-]+)+"
)
_SURNAME_PARTICLES = {"de", "di", "da", "del", "della", "dei", "degli", "lo", "la", "van", "von"}
_NOT_SURNAMES = {
    "il", "lo", "la", "le", "gli", "un", "una", "con", "per", "tra", "fra", "che", "del", "della",
    "dei", "delle", "srl", "spa", "snc", "sas", "s.r.l.", "s.p.a.", "ha", "è",
}  # fmt: skip
_NAME_TRAILING_STOP = {
    "via", "viale", "piazza", "corso", "largo", "strada", "tel", "email", "cod", "cf", "piva",
    "spett", "nato", "nata", "residente", "domiciliato", "domiciliata",
}  # fmt: skip

_COMPANY_SUFFIX = (
    r"(?:S\.r\.l\.s?|S\.R\.L\.|SRL|Srl|S\.p\.A\.|S\.P\.A\.|S\.p\.a\.|SPA|SpA|S\.n\.c\.|S\.N\.C\.|"
    r"SNC|Snc|S\.a\.s\.|S\.A\.S\.|SAS|Sas|Soc\.[ \t]?Coop\.|GmbH|Ltd|LLC|Inc\.|S\.A\.)"
)
_COMPANY_CAP = rf"(?!{_COMPANY_SUFFIX}(?![\w]))[{_UP}0-9][\w{_UP}{_LOW}&'’.\-]*"
_COMPANY_CONNECTOR = r"(?:di|del|della|dei|degli|e|ed|&|and|de)(?![\w])"
_COMPANY = re.compile(
    rf"(?<![\w])(?:(?:{_COMPANY_CAP}|{_COMPANY_CONNECTOR})[ \t]+){{0,6}}{_COMPANY_CAP}[ \t]+"
    rf"{_COMPANY_SUFFIX}(?![\w])"
)
_COMPANY_LEADING_STOP = {
    "il", "lo", "la", "le", "gli", "i", "un", "una", "uno", "con", "da", "di", "del", "della",
    "dei", "degli", "delle", "dello", "dal", "dalla", "in", "nel", "nella", "per", "tra", "fra",
    "su", "sul", "sulla", "a", "al", "alla", "allo", "ai", "agli", "e", "ed", "o", "presso",
    "spett.le", "spett.", "egr.", "egregio", "gentile", "ditta", "società", "azienda", "cliente",
    "fornitore", "sede", "contratto", "fattura", "ordine", "&", "and", "de",
}  # fmt: skip

_STREET_TYPE = (
    r"(?i:Via|Viale|V\.le|Piazza|P\.zza|Piazzale|Corso|C\.so|Largo|Vicolo|Strada|Località|Loc\.)"
)
_STREET_CONNECTOR = r"(?:(?:di|del|della|dei|degli|delle|dello|da|de|la|lo|il)[ \t]+|dell['’]|d['’])"
_STREET_WORD = rf"[{_UP}][\w{_UP}{_LOW}'’\-]+"
_STREET_FIRST_WORD = rf"[{_UP}][{_LOW}'’\-][\w{_UP}{_LOW}'’\-]*"
_STREET_NUMBER = r"(?:,?[ \t]*(?:n\.?°?[ \t]*|civ\.?[ \t]*)?\d{1,4}[ \t]?[A-Za-z]?(?:/[A-Za-z0-9]+)?)"
_CAP_CITY = (
    rf"(?:[ \t]*[,\-–]?[ \t]*\d{{5}}[ \t]+[{_UP}][\w{_LOW}'’\-]+(?:[ \t]+[{_UP}][\w{_LOW}'’\-]+){{0,2}}"
    rf"(?:[ \t]*\([A-Z]{{2}}\))?)"
)
_ADDRESS = re.compile(
    rf"(?<![\w]){_STREET_TYPE}[ \t]+(?:{_STREET_CONNECTOR})*{_STREET_FIRST_WORD}"
    rf"(?:[ \t]+(?:{_STREET_CONNECTOR})*{_STREET_WORD}){{0,3}}{_STREET_NUMBER}?{_CAP_CITY}?"
)

_PROFILE_HOSTS = (
    r"linkedin\.com|github\.com|gitlab\.com|bitbucket\.org|twitter\.com|x\.com|facebook\.com|"
    r"instagram\.com|tiktok\.com|youtube\.com|t\.me"
)
_URL = re.compile(
    rf"(?<![\w@.])(?:(?:https?://|www\.)[^\s<>()\[\]]+|(?:[a-z]{{2,3}}\.)?(?:{_PROFILE_HOSTS})/[^\s<>()\[\]]+)",
    re.IGNORECASE,
)

_NAME_LABEL = re.compile(
    rf"(?i:\b(?:Nome|Cognome|Nominativo|Referente|Intestatario|Intestataria|Titolare|Firmatario|"
    rf"Legale\s+rappresentante)\s*:[ \t]*)(?:{_TITLE}[ \t]+)?"
    rf"(?!{_TITLE})(?P<name>{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
)

_INSTITUTION = (
    r"(?:Liceo|Istituto|Università|Universita|Politecnico|Scuola|Fondazione|Associazione|Cooperativa|"
    r"Consorzio|Studio[ \t]+Legale|Studio[ \t]+Associato|Studio[ \t]+Notarile|Ospedale|Comune[ \t]+di|"
    r"Banca|Hotel|Ristorante|Azienda[ \t]+Agricola|Società[ \t]+Agricola|Ditta)"
)
_INSTITUTION_WORD = rf"(?:[{_UP}][\w{_UP}{_LOW}'’.\-]*|(?:di|del|della|dei|degli|delle|e|ed|&|de)(?![\w]))"
_INSTITUTION_NAME = re.compile(
    rf"(?<![\w]){_INSTITUTION}(?:[ \t]+{_INSTITUTION_WORD}){{1,5}}(?<![ \t])"
)

_GENERIC_CAP_WORDS = {"srl", "spa", "snc", "sas"}


class RuleDetector:
    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for finder in (
            self._emails,
            self._ibans,
            self._codici_fiscali,
            self._partite_iva,
            self._phones,
            self._urls,
            self._people,
            self._people_by_first_name,
            self._labeled_names,
            self._companies,
            self._institutions,
            self._addresses,
        ):
            spans.extend(finder(text))
        return spans

    # -- validated identifiers -----------------------------------------------------

    def _emails(self, text: str) -> Iterator[Span]:
        for match in _EMAIL.finditer(text):
            yield _span(match.start(), match.end(), "EMAIL", text, "rules:email", PRIORITY_VALIDATED)

    def _ibans(self, text: str) -> Iterator[Span]:
        for match in _IBAN_START.finditer(text):
            length = IBAN_LENGTHS.get(match.group(1).upper())
            if length is None:
                continue
            compact: list[str] = []
            cursor = match.start()
            while cursor < len(text) and len(compact) < length:
                char = text[cursor]
                if char.isascii() and char.isalnum():
                    compact.append(char)
                    cursor += 1
                elif char == " " and compact and cursor + 1 < len(text) and text[cursor + 1].isalnum():
                    cursor += 1
                else:
                    break
            if len(compact) == length and is_valid_iban("".join(compact)):
                yield _span(match.start(), cursor, "IBAN", text, "rules:iban", PRIORITY_VALIDATED)

    def _codici_fiscali(self, text: str) -> Iterator[Span]:
        seen: set[tuple[int, int]] = set()
        for match in _CF_PATTERN.finditer(text):
            if is_valid_cf(match.group(0)):
                seen.add((match.start(), match.end()))
                yield _span(match.start(), match.end(), "CF", text, "rules:cf", PRIORITY_VALIDATED)
        for match in _CF_LABELED.finditer(text):
            key = (match.start(1), match.end(1))
            if key not in seen:  # a labeled value is masked even if the checksum is wrong (typo)
                yield _span(*key, "CF", text, "rules:cf-labeled", PRIORITY_VALIDATED)

    def _partite_iva(self, text: str) -> Iterator[Span]:
        seen: set[tuple[int, int]] = set()
        for match in _PIVA_PATTERN.finditer(text):
            if is_valid_piva(match.group(1)):
                seen.add((match.start(), match.end()))
                yield _span(match.start(), match.end(), "PIVA", text, "rules:piva", PRIORITY_VALIDATED)
        for match in _PIVA_LABELED.finditer(text):
            key = (match.start(1), match.end(1))
            if key not in seen:
                yield _span(*key, "PIVA", text, "rules:piva-labeled", PRIORITY_VALIDATED)

    def _phones(self, text: str) -> Iterator[Span]:
        for match in _PHONE.finditer(text):
            if _THOUSANDS.fullmatch(match.group(0)):
                continue  # 300.000.000 is an amount, not a phone number
            digits = re.sub(r"\D", "", match.group(0))
            national = digits[2:] if digits.startswith("0039") else digits
            if national.startswith("39") and len(national) >= 11:
                national = national[2:]
            if 9 <= len(national) <= 11:
                yield _span(match.start(), match.end(), "TELEFONO", text, "rules:phone", PRIORITY_PATTERN)

    # -- heuristics ----------------------------------------------------------------

    def _people(self, text: str) -> Iterator[Span]:
        for match in _PERSON_WITH_TITLE.finditer(text):
            start, end = match.start("name"), match.end("name")
            words = list(re.finditer(r"\S+", text[start:end]))
            while words and words[-1].group(0).lower().strip(".,") in _NAME_TRAILING_STOP:
                words.pop()
            if not words:
                continue
            end = start + words[-1].end()
            yield _span(start, end, "PERSONA", text, "rules:title-name", PRIORITY_HEURISTIC)

    def _urls(self, text: str) -> Iterator[Span]:
        for match in _URL.finditer(text):
            end = match.end()
            while end > match.start() and text[end - 1] in ".,;:!?\"'":
                end -= 1
            yield _span(match.start(), end, "URL", text, "rules:url", PRIORITY_PATTERN + 10)

    def _labeled_names(self, text: str) -> Iterator[Span]:
        for match in _NAME_LABEL.finditer(text):
            start, end = match.start("name"), match.end("name")
            yield _span(start, end, "PERSONA", text, "rules:labeled-name", PRIORITY_HEURISTIC)

    def _people_by_first_name(self, text: str) -> Iterator[Span]:
        """"Mario Rossi", "Maria Chiara De Luca": a known first name followed by capitalised words."""
        for chain in _CAPITALISED_CHAINS.finditer(text):
            words = list(re.finditer(r"\S+", chain.group(0)))
            index = 0
            while index < len(words):
                word = words[index].group(0)
                if not (word[0].isupper() and is_first_name(word)):
                    index += 1
                    continue
                taken = 1
                has_surname = False
                while index + taken < len(words) and taken < 4:
                    following = words[index + taken].group(0)
                    bare = following.lower().strip(".,")
                    if bare in _NAME_TRAILING_STOP or bare in _NOT_SURNAMES:
                        break
                    after_particle = words[index + taken - 1].group(0).lower() in _SURNAME_PARTICLES
                    if is_first_name(following) and following[0].isupper() and not after_particle:
                        if has_surname:
                            break
                    else:
                        has_surname = True
                    taken += 1
                if taken >= 2 and has_surname:
                    start = chain.start() + words[index].start()
                    end = chain.start() + words[index + taken - 1].end()
                    yield _span(start, end, "PERSONA", text, "rules:first-name", PRIORITY_HEURISTIC)
                index += max(taken, 1)

    def _institutions(self, text: str) -> Iterator[Span]:
        for match in _INSTITUTION_NAME.finditer(text):
            yield _span(match.start(), match.end(), "AZIENDA", text, "rules:institution", PRIORITY_HEURISTIC)

    def _companies(self, text: str) -> Iterator[Span]:
        for match in _COMPANY.finditer(text):
            start, end = match.start(), match.end()
            tokens = list(re.finditer(r"\S+", text[start:end]))
            while len(tokens) > 2 and tokens[0].group(0).lower() in _COMPANY_LEADING_STOP:
                tokens.pop(0)
            start += tokens[0].start()
            yield _span(start, end, "AZIENDA", text, "rules:company-suffix", PRIORITY_HEURISTIC)

    def _addresses(self, text: str) -> Iterator[Span]:
        for match in _ADDRESS.finditer(text):
            yield _span(match.start(), match.end(), "INDIRIZZO", text, "rules:address", PRIORITY_HEURISTIC)


def _span(start: int, end: int, kind: str, text: str, source: str, priority: int) -> Span:
    return Span(start=start, end=end, kind=kind, text=text[start:end], source=source, priority=priority)
