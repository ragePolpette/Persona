"""analyze -> (review) -> apply -> verify: the "before sending to the AI" half of the loop.

The engine works on named text segments (a paragraph, a cell, a whole .md file), so file
adapters can plug in later. Detection is document-wide: a value found once is masked
everywhere it appears, and values already in the project vault are masked in new documents.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from persona.detect import GlossaryDetector, RuleDetector, Span, resolve_overlaps
from persona.detect.base import PRIORITY_ALIAS, PRIORITY_COLUMN, PRIORITY_KNOWN_VALUE, Detector
from persona.detect.rules import PROFILE_HOSTS
from persona.detect.vocabulary import HANDLE_STOP_WORDS, NAME_PARTICLES
from persona.edits import Edit, apply_edits
from persona.textnorm import FoldedText, Needle, fold
from persona.vault import Vault


@dataclass(slots=True)
class Segment:
    id: str
    text: str
    column_kind: str | None = None  # the whole text is a value of this kind (cell under a "Nome" header)


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
        found: list[Span] = _column_spans(segment)
        for detector in active:
            found.extend(detector.detect(segment.text))
        for span in found:
            span.segment = segment.id
        per_segment[segment.id] = _drop_allowed(found, vault)

    if propagate:
        searches = [
            (Needle(value, case_sensitive=exact), kind, "known-value", PRIORITY_KNOWN_VALUE)
            for value, (kind, exact) in _known_values(per_segment, vault).items()
        ]
        searches.extend(
            (Needle(value, case_sensitive=True), "PERSONA", "person-alias", PRIORITY_ALIAS)
            for value in sorted(_person_aliases(per_segment))
        )
        for segment in segment_list:
            folded = FoldedText(segment.text)
            found = per_segment[segment.id]
            taken = {(span.start, span.end) for span in found}
            extra: list[Span] = []
            for needle, kind, source, priority in searches:
                extra.extend(_occurrences(folded, segment, needle, kind, source, priority))
            found.extend(span for span in extra if (span.start, span.end) not in taken)

    spans: list[Span] = []
    for segment in segment_list:
        resolved = resolve_overlaps(_drop_allowed(per_segment[segment.id], vault))
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


def verify(texts: Mapping[str, str], vault: Vault, *, accepted: Iterable[str] = ()) -> list[Leak]:
    """Look for anything sensitive still present in the text about to be shared.

    Checks every value in the vault and glossary (case/accent-insensitive), and re-runs the
    rule detectors, so a sensitive value that was never approved is reported too.
    `accepted` are values the user explicitly chose to leave in (review "skip", `--exclude`).
    """
    accepted_keys = {fold(value.strip()) for value in accepted}
    rules = RuleDetector()
    searches = [
        (Needle(entry.value, case_sensitive=entry.case_sensitive), f"known value {entry.placeholder}")
        for entry in vault.entries
    ]
    searches.extend((Needle(form), f"glossary: {item.term}") for item in vault.glossary for form in item.all_forms)
    leaks: list[Leak] = []
    for segment_id, text in texts.items():
        folded = FoldedText(text)
        for needle, reason in searches:
            for start, end in folded.find(needle):
                leaks.append(Leak(segment_id, start, end, text[start:end], reason))
        for span in rules.detect(text):
            leaks.append(Leak(segment_id, span.start, span.end, span.text, f"detected {span.kind} ({span.source})"))
    return _dedupe(
        [
            leak
            for leak in leaks
            if not vault.is_allowed(leak.text) and fold(leak.text.strip()) not in accepted_keys
        ]
    )


def anonymize_text(text: str, vault: Vault, *, segment_id: str = "text") -> tuple[str, AnonymizeResult]:
    """Convenience for a single string: analyze + apply (no review step)."""
    analysis = analyze([Segment(segment_id, text)], vault)
    result = apply(analysis, vault)
    return result.texts[segment_id], result


# -- helpers --------------------------------------------------------------------------


def _column_spans(segment: Segment) -> list[Span]:
    """A cell under a recognised column header is masked whole, whatever the detectors say."""
    if not segment.column_kind:
        return []
    value = segment.text.strip()
    if sum(char.isalnum() for char in value) < 2:
        return []
    start = segment.text.index(value)
    return [
        Span(
            start=start,
            end=start + len(value),
            kind=segment.column_kind,
            text=value,
            source="column-header",
            priority=PRIORITY_COLUMN,
            segment=segment.id,
            # a lone surname such as "Verdi" must not mask the common word "verdi" elsewhere
            case_sensitive=segment.column_kind == "PERSONA" and len(value.split()) == 1,
            reason=f"cell in a {segment.column_kind} column",
        )
    ]


def _drop_allowed(spans: list[Span], vault: Vault | None) -> list[Span]:
    if vault is None or not vault.allowlist:
        return spans
    return [span for span in spans if not vault.is_allowed(span.text)]


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
                known.setdefault(span.text, (span.kind, span.case_sensitive))
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
                if len(bare) >= 3 and bare[0].isupper() and bare.lower() not in NAME_PARTICLES:
                    aliases.add(bare)
    return aliases


_PROFILE_PATH_PREFIXES = {"in", "pub", "company", "u", "user", "users", "profile", "people", "channel", "c"}


def _handle_tokens(text: str) -> list[str]:
    """Alphabetic name-like parts of a mail local part or a profile URL (`a.rossi`, `/in/mario-rossi`).

    Only profile sites (LinkedIn, GitHub, ...) have a person in the path: `acme.com/prodotti` has none.
    """
    if "@" in text and "/" not in text:
        handle = text.split("@", 1)[0]
    else:
        address = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", text, flags=re.IGNORECASE)
        host, _, path = address.partition("/")
        host = host.split(":", 1)[0].lower()
        if not any(host == known or host.endswith(f".{known}") for known in PROFILE_HOSTS):
            return []
        steps = [step for step in re.split(r"[?#]", path, maxsplit=1)[0].split("/") if step]
        while steps and steps[0].lower() in _PROFILE_PATH_PREFIXES:
            steps.pop(0)
        handle = steps[0].lstrip("@") if steps else ""
    tokens = re.split(r"[._\-+/0-9]+", handle)
    return [t for t in tokens if len(t) >= 4 and t.isalpha() and t.lower() not in HANDLE_STOP_WORDS]


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
    folded: FoldedText, segment: Segment, needle: Needle, kind: str, source: str, priority: int
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
            case_sensitive=needle.case_sensitive,
            reason=f"same as '{needle.text}'",
        )
        for start, end in folded.find(needle)
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


