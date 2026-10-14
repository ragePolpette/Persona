"""Case- and accent-insensitive search that maps matches back to the original text offsets."""

from __future__ import annotations

import re
import unicodedata


class FoldedText:
    """`text` lower-cased and stripped of accents, with a map from folded index to original index."""

    def __init__(self, text: str) -> None:
        self.original = text
        chars: list[str] = []
        index: list[int] = []
        for position, char in enumerate(text):
            for decomposed in unicodedata.normalize("NFD", char):
                if unicodedata.category(decomposed) == "Mn":
                    continue
                for lowered in decomposed.lower():
                    chars.append(lowered)
                    index.append(position)
        self.folded = "".join(chars)
        self._index = index

    def find_all(self, needle: str, *, case_sensitive: bool = False) -> list[tuple[int, int]]:
        """Whole-word occurrences of `needle` as (start, end) offsets in the original text.

        Whitespace inside the needle matches any run of whitespace. With `case_sensitive`
        the match is exact (accents included) and uses the original text directly.
        """
        return self.find(Needle(needle, case_sensitive=case_sensitive))

    def find(self, needle: Needle) -> list[tuple[int, int]]:
        """Like `find_all`, with a needle compiled once and reused across texts."""
        if needle.pattern is None:
            return []
        if needle.case_sensitive:
            return [
                (m.start(), m.end())
                for m in needle.pattern.finditer(self.original)
                if _is_whole_word(self.original, m.start(), m.end())
            ]
        hits: list[tuple[int, int]] = []
        for match in needle.pattern.finditer(self.folded):
            start = self._index[match.start()]
            end = self._index[match.end() - 1] + 1
            if _is_whole_word(self.original, start, end):
                hits.append((start, end))
        return hits


class Needle:
    """A search string compiled once, for `FoldedText.find` on many texts."""

    __slots__ = ("case_sensitive", "pattern", "text")

    def __init__(self, text: str, *, case_sensitive: bool = False) -> None:
        self.text = text
        self.case_sensitive = case_sensitive
        parts = text.split() if case_sensitive else FoldedText(" ".join(text.split())).folded.split()
        self.pattern = re.compile(r"\s+".join(re.escape(part) for part in parts)) if parts else None


def fold(text: str) -> str:
    return FoldedText(text).folded


def _is_whole_word(text: str, start: int, end: int) -> bool:
    if text[start].isalnum() and start > 0 and _is_word_char(text[start - 1]):
        return False
    return not (text[end - 1].isalnum() and end < len(text) and _is_word_char(text[end]))


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"
