"""Column headers that say every cell below them is sensitive ("Nome", "Email", "P.IVA"...)."""

from __future__ import annotations

import re

from persona.textnorm import fold

_HEADERS = {
    "PERSONA": (
        "nome", "cognome", "nome e cognome", "cognome e nome", "nome cognome", "cognome nome", "nominativo",
        "name", "first name", "last name", "surname", "full name", "given name", "family name",
    ),
    "AZIENDA": ("cliente", "customer", "client", "ragione sociale", "company", "company name"),
    "EMAIL": ("email", "e mail", "mail", "pec", "indirizzo email", "indirizzo e mail", "email address", "e mail address"),
    "TELEFONO": (
        "telefono", "tel", "cellulare", "cell", "numero di telefono", "phone", "telephone", "mobile", "phone number",
    ),
    "CF": ("codice fiscale", "cf", "c f", "tax code", "fiscal code"),
    "PIVA": ("p iva", "piva", "partita iva", "vat", "vat number", "vat no", "vat id"),
    "INDIRIZZO": ("indirizzo", "address", "street address"),
}  # fmt: skip
_BY_LABEL = {label: kind for kind, labels in _HEADERS.items() for label in labels}


def header_kind(text: str) -> str | None:
    """Kind of the values under a column titled `text`, or None if the header is not a known one."""
    label = re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()
    return _BY_LABEL.get(label)
