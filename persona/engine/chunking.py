from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(slots=True)
class TextChunk:
    index: int
    start: int
    end: int
    text: str


def _pick_split_point(text: str, cursor: int, tentative_end: int) -> int:
    for separator in ("\n\n", "\n", " "):
        split_at = text.rfind(separator, cursor, tentative_end)
        if split_at > cursor:
            return split_at + len(separator)
    return tentative_end


def iter_text_chunks(text: str, max_chars: int = 1200, overlap: int = 120) -> Iterator[TextChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    if overlap < 0:
        raise ValueError("overlap must be non-negative.")
    if not text:
        return

    cursor = 0
    index = 0
    text_length = len(text)
    while cursor < text_length:
        tentative_end = min(text_length, cursor + max_chars)
        end = tentative_end if tentative_end == text_length else _pick_split_point(text, cursor, tentative_end)
        if end <= cursor:
            end = tentative_end
        yield TextChunk(index=index, start=cursor, end=end, text=text[cursor:end])
        if end >= text_length:
            break
        cursor = max(0, end - overlap)
        index += 1
