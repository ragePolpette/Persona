from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True, frozen=True)
class Edit:
    """Replace text[start:end] with `text`. Offsets are in the segment's text."""

    start: int
    end: int
    text: str


def apply_edits(text: str, edits: Sequence[Edit]) -> str:
    pieces: list[str] = []
    cursor = 0
    for edit in sorted(edits, key=lambda e: e.start):
        if edit.start < cursor:
            raise ValueError("Overlapping edits.")
        pieces.append(text[cursor : edit.start])
        pieces.append(edit.text)
        cursor = edit.end
    pieces.append(text[cursor:])
    return "".join(pieces)
