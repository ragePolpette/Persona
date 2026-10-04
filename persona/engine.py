"""analyze -> (review) -> apply -> verify: the "before sending to the AI" half of the loop.

The engine works on named text segments (a paragraph, a cell, a whole .md file), so file
adapters can plug in later. Detection is document-wide: a value found once is masked
everywhere it appears, and values already in the project vault are masked in new documents.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from persona.edits import Edit, apply_edits
from persona.detect import GlossaryDetector, RuleDetector, Span, resolve_overlaps
from persona.detect.base import PRIORITY_ALIAS, PRIORITY_KNOWN_VALUE, Detector
from persona.textnorm import FoldedText
from persona.vault import Vault


@dataclass(slots=True)
class Segment:
    id: str
    text: str


@dataclass(slots=True)
class Analysis:
    segments: list[Segment]
    spans: list[Span]

    def approved(self) -> list[Span]:
        return [span for span in self.spans if span.approved]


@dataclass(slots=True)
class AnonymizeResult:
    texts: dict[str, str]
    edits: dict[str, list[Edit]] = field(default_factory=dict)
    placeholders: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class Leak:
    segment: str
    start: int
    end: int
    text: str
    reason: str


_PERSON_PARTICLES = {"de", "di", "da", "del", "della", "dei", "degli", "dello", "van", "von", "lo", "la"}


def analyze(
    segments: Sequence[Segment],
    vault: Vault | None = None,
    *,
    detectors: Sequence[Detector] | None = None,
    propagate: bool = True,
) -> Analysis:
    """Find everything sensitive in `segments`. Nothing is written to the vault here."""
    segment_list = list(segments)
    active: list[Detector] = list(detectors) if detectors is not None else [RuleDetector()]
    if detectors is None and vault is not None and vault.glossary:
        active.append(GlossaryDetector(vault.glossary))

    per_segment: dict[str, list[Span]] = {}
    for segment in segment_list:
        found: list[Span] = []
        for detector in active:
            found.extend(detector.detect(segment.text))
        for span in found:
            span.segment = segment.id
        per_segment[segment.id] = found

    if propagate:
        known = _known_values(per_segment, vault)
        aliases = _person_aliases(per_segment)
        for segment in segment_list:
            folded = FoldedText(segment.text)
            found = per_segment[segment.id]
            taken = {(span.start, span.end) for span in found}
            extra: list[Span] = []
            for value, (kind, exact) in known.items():
                extra.extend(
                    _occurrences(
                        folded, segment, value, kind, "known-value", PRIORITY_KNOWN_VALUE, case_sensitive=exact
                    )
                )
            for value in aliases:
                extra.extend(
                    _occurrences(
                        folded, segment, value, "PERSONA", "person-alias", PRIORITY_ALIAS, case_sensitive=True
                    )
                )
            found.extend(span for span in extra if (span.start, span.end) not in taken)

    spans: list[Span] = []
    for segment in segment_list:
        resolved = resolve_overlaps(per_segment[segment.id])
        spans.extend(_merge_adjacent_people(resolved, segment.text))
    return Analysis(segments=segment_list, spans=spans)


def apply(analysis: Analysis, vault: Vault) -> AnonymizeResult:
    """Replace the approved spans with placeholders, registering new values in the vault.

    The caller must `vault.save()` afterwards.
    """
    by_segment: dict[str, list[Span]] = {}
    for span in analysis.approved():
        by_segment.setdefault(span.segment, []).append(span)

    result = AnonymizeResult(texts={})
    for segment in analysis.segments:
        edits: list[Edit] = []
        for span in sorted(by_segment.get(segment.id, []), key=lambda s: s.start):
            placeholder = vault.placeholder_for(span.kind, span.text, case_sensitive=span.case_sensitive)
            edits.append(Edit(span.start, span.end, placeholder))
            result.placeholders[placeholder] += 1
        result.edits[segment.id] = edits
        result.texts[segment.id] = apply_edits(segment.text, edits)
    return result


def verify(texts: Mapping[str, str], vault: Vault) -> list[Leak]:
    """Look for anything sensitive still present in the text about to be shared.

    Checks every value in the vault and glossary (case/accent-insensitive), and re-runs the
    rule detectors, so a sensitive value that was never approved is reported too.
    """
    rules = RuleDetector()
    leaks: list[Leak] = []
    for segment_id, text in texts.items():
        folded = FoldedText(text)
        for entry in vault.entries:
            for start, end in folded.find_all(entry.value, case_sensitive=entry.case_sensitive):
                leaks.append(Leak(segment_id, start, end, text[start:end], f"known value {entry.placeholder}"))
        for item in vault.glossary:
            for form in item.all_forms:
                for start, end in folded.find_all(form):
                    leaks.append(Leak(segment_id, start, end, text[start:end], f"glossary: {item.term}"))
        for span in rules.detect(text):
            leaks.append(Leak(segment_id, span.start, span.end, span.text, f"detected {span.kind} ({span.source})"))
    return _dedupe(leaks)


def anonymize_text(text: str, vault: Vault, *, segment_id: str = "text") -> tuple[str, AnonymizeResult]:
    """Convenience for a single string: analyze + apply (no review step)."""
    analysis = analyze([Segment(segment_id, text)], vault)
    result = apply(analysis, vault)
    return result.texts[segment_id], result


# -- helpers --------------------------------------------------------------------------


def _known_values(
    per_segment: Mapping[str, list[Span]], vault: Vault | None
) -> dict[str, tuple[str, bool]]:
    """value -> (kind, case_sensitive) for everything already known to be sensitive."""
    known: dict[str, tuple[str, bool]] = {}
    if vault is not None:
        for entry in vault.entries:
            known[entry.value] = (entry.kind, entry.case_sensitive)
    for spans in per_segment.values():
        for span in spans:
            if span.priority > PRIORITY_ALIAS:
                known.setdefault(span.text, (span.kind, False))
    return known


def _person_aliases(per_segment: Mapping[str, list[Span]]) -> set[str]:
    """Bare first/last names of detected people ("Rossi" after "Mario Rossi").

    Also the name-like parts of e-mail addresses and profile URLs: `zeno.cosini@...`
    reveals that "Zeno" and "Cosini" are names, even with no title in the text.
    """
    aliases: set[str] = set()
    for spans in per_segment.values():
        for span in spans:
            if span.kind in {"EMAIL", "URL"}:
                for token in _handle_tokens(span.text):
                    aliases.update({token.capitalize(), token.upper()})
                continue
            if span.kind != "PERSONA":
                continue
            words = span.text.split()
            if len(words) < 2:
                continue
            for word in words:
                bare = word.strip(".,;:'’")
                if len(bare) >= 3 and bare[0].isupper() and bare.lower() not in _PERSON_PARTICLES:
                    aliases.add(bare)
    return aliases


_ROLE_WORDS = {
    "info", "ufficio", "amministrazione", "acquisti", "segreteria", "contatti", "contact", "mail", "email",
    "pec", "admin", "support", "supporto", "sales", "vendite", "office", "noreply", "posta", "hello",
    "ciao", "commerciale", "fatture", "fatturazione", "ordini", "assistenza", "direzione", "personale",
    "linkedin", "github", "gitlab", "twitter", "facebook", "instagram", "youtube", "profile", "profilo",
    "company", "www", "http", "https", "gmail", "hotmail", "outlook", "yahoo", "libero", "example",
}  # fmt: skip


def _handle_tokens(text: str) -> list[str]:
    """Alphabetic name-like parts of a mail local part or URL path (`a.rossi`, `/in/mario-rossi`)."""
    local = text.split("@", 1)[0] if "@" in text else text.split("/", 1)[1] if "/" in text else ""
    if "/" in local:
        local = local.split("/", 2)[1] if local.startswith("in/") else local
    tokens = re.split(r"[._\-+/0-9]+", local)
    return [t for t in tokens if len(t) >= 4 and t.isalpha() and t.lower() not in _ROLE_WORDS]


def _merge_adjacent_people(spans: list[Span], text: str) -> list[Span]:
    """"Zeno" + "Cosini" found separately become one PERSONA block."""
    merged: list[Span] = []
    for span in spans:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.kind == "PERSONA"
            and span.kind == "PERSONA"
            and previous.case_sensitive == span.case_sensitive
            and text[previous.end : span.start] != ""
            and text[previous.end : span.start].strip(" \t") == ""
        ):
            previous.end = span.end
            previous.text = text[previous.start : previous.end]
            previous.priority = max(previous.priority, span.priority)
            previous.source = f"{previous.source}+{span.source}"
            continue
        merged.append(span)
    return merged


def _occurrences(
    folded: FoldedText,
    segment: Segment,
    value: str,
    kind: str,
    source: str,
    priority: int,
    *,
    case_sensitive: bool = False,
) -> list[Span]:
    return [
        Span(
            start=start,
            end=end,
            kind=kind,
            text=segment.text[start:end],
            source=source,
            priority=priority,
            segment=segment.id,
            case_sensitive=case_sensitive,
            reason=f"same as '{value}'",
        )
        for start, end in folded.find_all(value, case_sensitive=case_sensitive)
    ]


def _dedupe(leaks: list[Leak]) -> list[Leak]:
    seen: set[tuple[str, int, int]] = set()
    unique: list[Leak] = []
    for leak in sorted(leaks, key=lambda item: (item.segment, item.start, item.end)):
        key = (leak.segment, leak.start, leak.end)
        if key not in seen:
            seen.add(key)
            unique.append(leak)
    return unique


