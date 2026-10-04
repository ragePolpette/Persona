"""Interactive review of what is about to be masked.

The detectors are conservative but not perfect, so before anything is shared a person can:
mask or skip each distinct value, mark a value as "never mask" (stored in the vault, so the same
false positive never comes back), and add names the detectors missed to the glossary.
Prompting is injected, so the flow is testable and a UI can reuse it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from persona.engine import Analysis
from persona.placeholders import KINDS
from persona.vault import Vault

Ask = Callable[[str, str], str]  # (prompt, default) -> answer
Say = Callable[[str], None]

_CONTEXT = 32
_CHOICES = {"": "mask", "m": "mask", "s": "skip", "n": "never", "a": "all"}


@dataclass(slots=True)
class Group:
    kind: str
    text: str
    count: int
    sources: set[str] = field(default_factory=set)
    contexts: list[str] = field(default_factory=list)


def group_spans(analysis: Analysis) -> list[Group]:
    """Distinct (kind, text) values with a couple of context snippets each."""
    segments = {segment.id: segment.text for segment in analysis.segments}
    groups: dict[tuple[str, str], Group] = {}
    for span in analysis.spans:
        group = groups.setdefault((span.kind, span.text), Group(span.kind, span.text, 0))
        group.count += 1
        group.sources.add(span.source)
        if len(group.contexts) < 2:
            text = segments[span.segment]
            before = text[max(0, span.start - _CONTEXT) : span.start].replace("\n", " ")
            after = text[span.end : span.end + _CONTEXT].replace("\n", " ")
            group.contexts.append(f"…{before}«{span.text}»{after}…")
    return sorted(groups.values(), key=lambda g: (g.kind, g.text.lower()))


def render(group: Group) -> str:
    lines = [f"{group.kind}  x{group.count}  {group.text!r}  ({', '.join(sorted(group.sources))})"]
    lines.extend(f"    {context}" for context in group.contexts)
    return "\n".join(lines)


def run_review(
    analyze_again: Callable[[], Analysis],
    vault: Vault,
    ask: Ask,
    say: Say,
) -> Analysis:
    """Review loop. `analyze_again` re-runs detection (needed after glossary/allowlist changes)."""
    skipped: set[str] = set()
    decided: set[str] = set()
    mask_all = False
    while True:
        analysis = analyze_again()
        for group in group_spans(analysis):
            if group.text in decided:
                continue
            decided.add(group.text)
            if mask_all:
                continue
            say(render(group))
            choice = _choose(ask)
            if choice == "skip":
                skipped.add(group.text)
            elif choice == "never":
                vault.allow(group.text)
                skipped.add(group.text)
            elif choice == "all":
                mask_all = True
        name = ask("Anything missed? Name to add to the glossary (blank = done)", "").strip()
        if not name:
            break
        vault.add_glossary(name, _choose_kind(ask, say))
        say(f"Added to glossary: {name}")
    for span in analysis.spans:
        span.approved = span.text not in skipped
    return analysis


def _choose(ask: Ask) -> str:
    while True:
        answer = ask("[m]ask (default) / [s]kip this time / [n]ever mask / [a]ll the rest", "m").strip().lower()
        if answer in _CHOICES:
            return _CHOICES[answer]


def _choose_kind(ask: Ask, say: Say) -> str:
    while True:
        kind = ask(f"Kind ({', '.join(KINDS)})", "PERSONA").strip().upper()
        if kind in KINDS:
            return kind
        say(f"Unknown kind '{kind}'.")
