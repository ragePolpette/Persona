"""Short, readable placeholders that survive an AI's rewriting: [PERSONA_1], [AZIENDA_2], ...

The kind tells the AI what the thing is, so it can write around it naturally.
Finding placeholders in AI output is deliberately tolerant (case, brackets, markdown escapes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = ("PERSONA", "AZIENDA", "EMAIL", "TELEFONO", "IBAN", "CF", "PIVA", "INDIRIZZO", "ALTRO")


def format_placeholder(kind: str, number: int) -> str:
    return f"[{kind}_{number}]"


@dataclass(slots=True)
class PlaceholderRef:
    kind: str
    number: int
    start: int
    end: int
    raw: str
    exact: bool  # raw is exactly the canonical "[KIND_N]" form

    @property
    def canonical(self) -> str:
        return format_placeholder(self.kind, self.number)


_KIND_ALTERNATION = "|".join(KINDS)
_PATTERN = re.compile(
    rf"(?:(?P<open>\\?[\[({{<【])|(?<![A-Za-z0-9]))"
    rf"(?P<kind>{_KIND_ALTERNATION})"
    rf"(?:\\?_|[ \t\-]+)"
    rf"(?P<number>\d{{1,5}})"
    rf"(?P<close>\\?[\])}}>】])?",
    re.IGNORECASE,
)


def find_placeholders(text: str) -> list[PlaceholderRef]:
    """Every placeholder-looking token in `text`, tolerating the usual LLM mangling.

    Accepted: any bracket pair ([ ( { <), any case, `_` / space / `-` as separator, markdown
    escapes (`\\[PERSONA\\_1\\]`). Without brackets only the exact upper-case `KIND_N` form counts.
    """
    refs: list[PlaceholderRef] = []
    for match in _PATTERN.finditer(text):
        opened, closed = match.group("open"), match.group("close")
        if bool(opened) != bool(closed):
            # one-sided bracket: treat the token as unbracketed
            opened = closed = None
            start, end = _strip_side(match)
        else:
            start, end = match.start(), match.end()
        raw = text[start:end]
        if not opened:
            body = raw
            if not (body.isupper() and "_" in body and "\\" not in body):
                continue
            if end < len(text) and (text[end].isalnum() or text[end] == "_"):
                continue
        kind = match.group("kind").upper()
        number = int(match.group("number"))
        refs.append(
            PlaceholderRef(
                kind=kind,
                number=number,
                start=start,
                end=end,
                raw=raw,
                exact=raw == format_placeholder(kind, number),
            )
        )
    return refs


def _strip_side(match: re.Match[str]) -> tuple[int, int]:
    start = match.start("kind")
    end = match.end("number")
    return start, end
