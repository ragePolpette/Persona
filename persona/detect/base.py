from __future__ import annotations

import heapq
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import Protocol

from persona.detect.vocabulary import EDGE_WORDS

# Higher wins when two detections overlap.
PRIORITY_VALIDATED = 100  # checksum-validated: IBAN, codice fiscale, P.IVA, e-mail
PRIORITY_GLOSSARY = 90
PRIORITY_COLUMN = 85  # a cell under a column header such as "Nome" or "Email"
PRIORITY_KNOWN_VALUE = 80  # a value already seen in this document or in the project vault
PRIORITY_PATTERN = 60  # phone numbers
PRIORITY_HEURISTIC = 50  # titles + names, company suffixes, street addresses
PRIORITY_ALIAS = 40  # bare surname / first name of a detected person


@dataclass(slots=True)
class Span:
    start: int
    end: int
    kind: str
    text: str
    source: str
    priority: int
    segment: str = ""
    approved: bool = True
    case_sensitive: bool = False
    reason: str = field(default="")

    @property
    def length(self) -> int:
        return self.end - self.start


class Detector(Protocol):
    def detect(self, text: str) -> list[Span]: ...


_EDGE_PUNCTUATION = " \t\r\n,;:-–"


def resolve_overlaps(spans: Sequence[Span]) -> list[Span]:
    """Greedy: best priority first, then longest.

    A span that loses to a better one is not simply dropped: whatever part of it the winner
    does not cover is kept as a smaller span, so a greedy heuristic match can never hide
    a sensitive value behind a neighbour ("Giulia Marchetti di Tessitura Valdarno S.r.l.").
    """
    order = count()
    pending = [(-span.priority, -span.length, span.start, next(order), span) for span in spans]
    heapq.heapify(pending)
    kept: list[Span] = []  # non-overlapping, sorted by start (and therefore by end)
    kept_ends: list[int] = []
    while pending:
        span = heapq.heappop(pending)[-1]
        first = bisect_right(kept_ends, span.start)
        last = first
        while last < len(kept) and kept[last].start < span.end:
            last += 1
        if first == last:
            kept.insert(first, span)
            kept_ends.insert(first, span.end)
            continue
        for part in _uncovered_parts(span, kept[first:last]):
            heapq.heappush(pending, (-part.priority, -part.length, part.start, next(order), part))
    return sorted(kept, key=lambda s: (s.start, s.end))


def _uncovered_parts(span: Span, blockers: Sequence[Span]) -> list[Span]:
    parts: list[Span] = []
    cursor = span.start
    for blocker in sorted(blockers, key=lambda s: s.start):
        if blocker.start > cursor:
            parts.append(_trimmed(span, cursor, blocker.start))
        cursor = max(cursor, blocker.end)
    if cursor < span.end:
        parts.append(_trimmed(span, cursor, span.end))
    return [part for part in parts if part is not None]


def _trimmed(span: Span, start: int, end: int) -> Span | None:
    text = span.text[start - span.start : end - span.start]
    while True:
        stripped = text.strip(_EDGE_PUNCTUATION)
        words = stripped.split(None, 1)
        if len(words) == 2 and words[0].lower() in EDGE_WORDS:
            stripped = words[1]
        else:
            last = stripped.rsplit(None, 1)
            if len(last) == 2 and last[1].lower() in EDGE_WORDS:
                stripped = last[0]
        if stripped == text:
            break
        text = stripped
    if len(text) < 3 or not any(char.isalnum() for char in text):
        return None
    offset = span.text.index(text, start - span.start)
    return Span(
        start=span.start + offset,
        end=span.start + offset + len(text),
        kind=span.kind,
        text=text,
        source=span.source,
        priority=span.priority,
        segment=span.segment,
        approved=span.approved,
        case_sensitive=span.case_sensitive,
        reason=span.reason or "remainder of a larger match",
    )
