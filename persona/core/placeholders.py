from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass

from persona.exceptions import PlaceholderValidationError

PLACEHOLDER_OPEN = "[["
PLACEHOLDER_CLOSE = "]]"
PLACEHOLDER_PREFIX = "[[P1|"
PLACEHOLDER_SUFFIX = PLACEHOLDER_CLOSE
CURRENT_PLACEHOLDER_VERSION = "P2"
TOKEN_RE = re.compile(r"^[A-Z0-9]{6,32}$")
INTEGRITY_RE = re.compile(r"^[A-Z0-9]{4,16}$")
PLACEHOLDER_CANDIDATE_RE = re.compile(r"\[\[(?P<body>.*?)\]\]")


@dataclass(slots=True)
class ParsedPlaceholder:
    version: str
    token_id: str
    masked_value: str
    raw_value: str
    start: int
    end: int
    integrity_tag: str | None = None


@dataclass(slots=True)
class PlaceholderCandidate:
    raw_value: str
    start: int
    end: int
    parsed: ParsedPlaceholder | None = None
    error: str | None = None


def validate_masked_payload(masked_value: str) -> None:
    if "|" in masked_value or PLACEHOLDER_CLOSE in masked_value:
        raise PlaceholderValidationError("Masked payload contains reserved placeholder delimiters.")


def validate_token_id(token_id: str) -> None:
    if not TOKEN_RE.fullmatch(token_id):
        raise PlaceholderValidationError("Placeholder token format is invalid.")


def validate_integrity_tag(integrity_tag: str) -> None:
    if not INTEGRITY_RE.fullmatch(integrity_tag):
        raise PlaceholderValidationError("Placeholder integrity marker format is invalid.")


def compute_placeholder_integrity_tag(
    root_key: bytes,
    token_id: str,
    masked_value: str,
    length: int = 6,
) -> str:
    material = f"placeholder:{token_id}:{masked_value}".encode("utf-8")
    digest = hmac.new(root_key, material, hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")[:length]


def build_placeholder(token_id: str, masked_value: str, integrity_tag: str | None = None) -> str:
    validate_token_id(token_id)
    validate_masked_payload(masked_value)
    if integrity_tag:
        validate_integrity_tag(integrity_tag)
        return f"{PLACEHOLDER_OPEN}{CURRENT_PLACEHOLDER_VERSION}|{token_id}|{integrity_tag}|{masked_value}{PLACEHOLDER_CLOSE}"
    return f"{PLACEHOLDER_PREFIX}{token_id}|{masked_value}{PLACEHOLDER_CLOSE}"


def parse_placeholder(raw_value: str) -> ParsedPlaceholder:
    if not raw_value.startswith(PLACEHOLDER_OPEN) or not raw_value.endswith(PLACEHOLDER_CLOSE):
        raise PlaceholderValidationError("Invalid placeholder wrapper.")
    body = raw_value[len(PLACEHOLDER_OPEN) : -len(PLACEHOLDER_CLOSE)]
    parts = body.split("|")
    if not parts:
        raise PlaceholderValidationError("Malformed placeholder body.")

    version = parts[0]
    if version == "P1":
        if len(parts) != 3:
            raise PlaceholderValidationError("Malformed legacy placeholder body.")
        _, token_id, masked_value = parts
        validate_token_id(token_id)
        validate_masked_payload(masked_value)
        return ParsedPlaceholder(
            version=version,
            token_id=token_id,
            masked_value=masked_value,
            raw_value=raw_value,
            start=0,
            end=len(raw_value),
            integrity_tag=None,
        )

    if version == CURRENT_PLACEHOLDER_VERSION:
        if len(parts) != 4:
            raise PlaceholderValidationError("Malformed placeholder body.")
        _, token_id, integrity_tag, masked_value = parts
        validate_token_id(token_id)
        validate_integrity_tag(integrity_tag)
        validate_masked_payload(masked_value)
        return ParsedPlaceholder(
            version=version,
            token_id=token_id,
            masked_value=masked_value,
            raw_value=raw_value,
            start=0,
            end=len(raw_value),
            integrity_tag=integrity_tag,
        )

    raise PlaceholderValidationError(f"Unsupported placeholder version '{version}'.")


def scan_placeholder_candidates(text: str) -> list[PlaceholderCandidate]:
    candidates: list[PlaceholderCandidate] = []
    matched_starts: set[int] = set()
    for match in PLACEHOLDER_CANDIDATE_RE.finditer(text):
        raw_value = match.group(0)
        candidate = PlaceholderCandidate(raw_value=raw_value, start=match.start(), end=match.end())
        try:
            parsed = parse_placeholder(raw_value)
            parsed.start = match.start()
            parsed.end = match.end()
            candidate.parsed = parsed
        except PlaceholderValidationError as exc:
            candidate.error = str(exc)
        candidates.append(candidate)
        matched_starts.add(match.start())

    cursor = 0
    while True:
        start = text.find(f"{PLACEHOLDER_OPEN}P", cursor)
        if start == -1:
            break
        if start not in matched_starts:
            snippet = text[start : min(len(text), start + 48)]
            candidates.append(
                PlaceholderCandidate(
                    raw_value=snippet,
                    start=start,
                    end=min(len(text), start + len(snippet)),
                    error="Unterminated placeholder wrapper.",
                )
            )
        cursor = start + 2

    return sorted(candidates, key=lambda item: item.start)
