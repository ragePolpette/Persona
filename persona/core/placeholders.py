from __future__ import annotations

from dataclasses import dataclass

from persona.exceptions import PlaceholderValidationError

PLACEHOLDER_PREFIX = "[[P1|"
PLACEHOLDER_SUFFIX = "]]"


@dataclass(slots=True)
class ParsedPlaceholder:
    token_id: str
    masked_value: str
    raw_value: str
    start: int
    end: int


def validate_masked_payload(masked_value: str) -> None:
    if "|" in masked_value or PLACEHOLDER_SUFFIX in masked_value:
        raise PlaceholderValidationError("Masked payload contains reserved placeholder delimiters.")


def build_placeholder(token_id: str, masked_value: str) -> str:
    validate_masked_payload(masked_value)
    return f"{PLACEHOLDER_PREFIX}{token_id}|{masked_value}{PLACEHOLDER_SUFFIX}"


def parse_placeholder(raw_value: str) -> ParsedPlaceholder:
    if not raw_value.startswith(PLACEHOLDER_PREFIX) or not raw_value.endswith(PLACEHOLDER_SUFFIX):
        raise PlaceholderValidationError("Invalid placeholder wrapper.")
    body = raw_value[len(PLACEHOLDER_PREFIX) : -len(PLACEHOLDER_SUFFIX)]
    try:
        token_id, masked_value = body.split("|", 1)
    except ValueError as exc:
        raise PlaceholderValidationError("Malformed placeholder body.") from exc
    if not token_id:
        raise PlaceholderValidationError("Placeholder token is missing.")
    validate_masked_payload(masked_value)
    return ParsedPlaceholder(
        token_id=token_id,
        masked_value=masked_value,
        raw_value=raw_value,
        start=0,
        end=len(raw_value),
    )


def scan_placeholders(text: str) -> list[ParsedPlaceholder]:
    placeholders: list[ParsedPlaceholder] = []
    cursor = 0
    while True:
        start = text.find(PLACEHOLDER_PREFIX, cursor)
        if start == -1:
            return placeholders
        token_sep = text.find("|", start + len(PLACEHOLDER_PREFIX))
        end = text.find(PLACEHOLDER_SUFFIX, token_sep + 1 if token_sep != -1 else start + len(PLACEHOLDER_PREFIX))
        if token_sep == -1 or end == -1:
            cursor = start + len(PLACEHOLDER_PREFIX)
            continue
        raw_value = text[start : end + len(PLACEHOLDER_SUFFIX)]
        parsed = parse_placeholder(raw_value)
        parsed.start = start
        parsed.end = end + len(PLACEHOLDER_SUFFIX)
        placeholders.append(parsed)
        cursor = parsed.end

