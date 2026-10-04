"""The "AI gave me back a file" half of the loop: put the original values back.

Works on any text, not on a specific file: the AI's output is never the file you sent.
Placeholders are found tolerantly; anything the AI invented or dropped is reported.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

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


def restore_text(text: str, vault: Vault, *, expected: Iterable[str] | None = None) -> RestoreReport:
    """Restore `text`. `expected` = placeholders in the document that was sent, to spot dropped ones."""
    report = RestoreReport(text=text)
    pieces: list[str] = []
    cursor = 0
    for ref in find_placeholders(text):
        entry = vault.lookup(ref.kind, ref.number)
        pieces.append(text[cursor : ref.start])
        cursor = ref.end
        if entry is None:
            report.invented.append(ref.raw)
            pieces.append(ref.raw)
            continue
        pieces.append(entry.value)
        report.restored[entry.placeholder] += 1
        if not ref.exact:
            report.altered.append((ref.raw, ref.canonical))
    pieces.append(text[cursor:])
    report.text = "".join(pieces)
    if expected is not None:
        report.missing = sorted(set(expected) - set(report.restored))
    return report


def placeholders_in(text: str) -> set[str]:
    return {ref.canonical for ref in find_placeholders(text)}
