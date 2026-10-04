from __future__ import annotations

from typing import Sequence

from persona.detect.base import PRIORITY_GLOSSARY, Span
from persona.textnorm import FoldedText
from persona.vault import GlossaryTerm


class GlossaryDetector:
    """The user's own list of names to always mask: the highest-recall detector there is."""

    def __init__(self, terms: Sequence[GlossaryTerm]) -> None:
        self.terms = list(terms)

    def detect(self, text: str) -> list[Span]:
        folded = FoldedText(text)
        spans: list[Span] = []
        for item in self.terms:
            for form in item.all_forms:
                for start, end in folded.find_all(form):
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
