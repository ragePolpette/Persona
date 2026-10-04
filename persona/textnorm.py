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
        parts = needle.split()
        if not parts:
            return []
        if case_sensitive:
            pattern = re.compile(r"\s+".join(re.escape(part) for part in parts))
            return [
                (m.start(), m.end())
                for m in pattern.finditer(self.original)
                if _is_whole_word(self.original, m.start(), m.end())
            ]
        folded_needle = FoldedText(" ".join(parts)).folded.split()
        if not folded_needle:
            return []
        pattern = re.compile(r"\s+".join(re.escape(part) for part in folded_needle))
        hits: list[tuple[int, int]] = []
        for match in pattern.finditer(self.folded):
            start = self._index[match.start()]
            end = self._index[match.end() - 1] + 1
            if _is_whole_word(self.original, start, end):
                hits.append((start, end))
        return hits


def fold(text: str) -> str:
    return FoldedText(text).folded


def _is_whole_word(text: str, start: int, end: int) -> bool:
    if text[start].isalnum() and start > 0 and _is_word_char(text[start - 1]):
        return False
    if text[end - 1].isalnum() and end < len(text) and _is_word_char(text[end]):
        return False
    return True


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"
