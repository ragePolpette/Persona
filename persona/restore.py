"""The "AI gave me back a file" half of the loop: put the original values back.

Works on any text, not on a specific file: the AI's output is never the file you sent.
Placeholders are found tolerantly; anything the AI invented or dropped is reported.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from persona.edits import Edit, apply_edits
from persona.engine import Segment
from persona.placeholders import find_placeholders
from persona.vault import Vault


@dataclass(slots=True)
class RestoreReport:
    text: str
    restored: Counter[str] = field(default_factory=Counter)
    altered: list[tuple[str, str]] = field(default_factory=list)  # (what the AI wrote, canonical form)
    invented: list[str] = field(default_factory=list)  # looks like a placeholder, not in the vault
    missing: list[str] = field(default_factory=list)  # was sent to the AI, absent from its output

    @property
    def clean(self) -> bool:
        return not self.invented and not self.missing


def restore_segments(
    segments: Sequence[Segment], vault: Vault, *, expected: Iterable[str] | None = None
) -> tuple[dict[str, list[Edit]], RestoreReport]:
    """Edits that restore every segment, plus one aggregated report."""
    report = RestoreReport(text="")
    edits_by_segment: dict[str, list[Edit]] = {}
    for segment in segments:
        edits: list[Edit] = []
        for ref in find_placeholders(segment.text):
            entry = vault.lookup(ref.kind, ref.number)
            if entry is None:
                report.invented.append(ref.raw)
                continue
            edits.append(Edit(ref.start, ref.end, entry.value))
            report.restored[entry.placeholder] += 1
            if not ref.exact:
                report.altered.append((ref.raw, ref.canonical))
        edits_by_segment[segment.id] = edits
    if expected is not None:
        report.missing = sorted(set(expected) - set(report.restored))
    return edits_by_segment, report


def restore_text(text: str, vault: Vault, *, expected: Iterable[str] | None = None) -> RestoreReport:
    """Restore a single string. `expected` = placeholders in the document that was sent."""
    segment = Segment("text", text)
    edits, report = restore_segments([segment], vault, expected=expected)
    report.text = apply_edits(text, edits["text"])
    return report


def placeholders_in(text: str) -> set[str]:
    return {ref.canonical for ref in find_placeholders(text)}
