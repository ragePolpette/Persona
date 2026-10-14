from __future__ import annotations

from collections.abc import Sequence

from persona.detect.base import PRIORITY_GLOSSARY, Span
from persona.textnorm import FoldedText, Needle
from persona.vault import GlossaryTerm


class GlossaryDetector:
    """The user's own list of names to always mask: the highest-recall detector there is."""

    def __init__(self, terms: Sequence[GlossaryTerm]) -> None:
        self.terms = list(terms)
        self._needles = [(item, Needle(form)) for item in self.terms for form in item.all_forms]

    def detect(self, text: str) -> list[Span]:
        folded = FoldedText(text)
        spans: list[Span] = []
        for item, needle in self._needles:
            for start, end in folded.find(needle):
                spans.append(
                    Span(
                        start=start,
                        end=end,
                        kind=item.kind,
                        text=text[start:end],
                        source="glossary",
                        priority=PRIORITY_GLOSSARY,
                        reason=f"glossary: {item.term}",
                    )
                )
        return spans
