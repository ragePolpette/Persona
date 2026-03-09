from __future__ import annotations

import re
import unicodedata

WHITESPACE_RE = re.compile(r"\s+")
NON_DIGIT_RE = re.compile(r"\D+")


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return normalized.strip()


def collapse_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", normalize_text(value))


def canonicalize_value(entity_type: str, value: str) -> str:
    normalized = normalize_text(value)
    if entity_type == "EMAIL_ADDRESS":
        return WHITESPACE_RE.sub("", normalized).casefold()
    if entity_type == "PHONE_NUMBER":
        prefix = "+" if normalized.startswith("+") else ""
        digits = NON_DIGIT_RE.sub("", normalized)
        return prefix + digits
    if entity_type in {"IBAN", "IT_FISCAL_CODE"}:
        return WHITESPACE_RE.sub("", normalized).upper()
    return collapse_whitespace(normalized).casefold()


def canonicalize_token_material(entity_type: str, value: str) -> bytes:
    canonical = canonicalize_value(entity_type, value)
    return f"{entity_type}:{canonical}".encode("utf-8")

