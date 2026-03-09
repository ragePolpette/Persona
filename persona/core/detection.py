from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import spacy
from presidio_analyzer import Pattern, PatternRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.predefined_recognizers import PhoneRecognizer

from persona.config import DEFAULT_ENABLED_ENTITIES, DEFAULT_SPACY_MODEL
from persona.exceptions import DetectionUnavailableError
from persona.models.entities import DetectionMatch, TextSegment

SPACY_LABEL_MAP = {
    "PERSON": "PERSON",
    "PER": "PERSON",
    "ORG": "ORGANIZATION",
}


class EmailAddressRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="email_address",
                regex=r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b",
                score=0.85,
            )
        ]
        super().__init__(supported_entity="EMAIL_ADDRESS", patterns=patterns)


class IbanRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="iban",
                regex=r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
                score=0.75,
            )
        ]
        super().__init__(supported_entity="IBAN", patterns=patterns)


class ItalianFiscalCodeRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="italian_fiscal_code",
                regex=r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b",
                score=0.85,
            )
        ]
        super().__init__(supported_entity="IT_FISCAL_CODE", patterns=patterns)


@dataclass(slots=True)
class DetectionCandidate:
    entity_type: str
    start: int
    end: int
    score: float
    text: str


def parse_enabled_entities(raw_entities: str | None) -> tuple[str, ...]:
    if not raw_entities:
        return DEFAULT_ENABLED_ENTITIES
    entities = tuple(item.strip().upper() for item in raw_entities.split(",") if item.strip())
    if not entities:
        return DEFAULT_ENABLED_ENTITIES
    return entities


def build_context(text: str, start: int, end: int, radius: int = 24) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return f"{text[left:start]}[{text[start:end]}]{text[end:right]}"


def _deduplicate_candidates(candidates: Iterable[DetectionCandidate]) -> list[DetectionCandidate]:
    unique: dict[tuple[str, int, int, str], DetectionCandidate] = {}
    for candidate in candidates:
        key = (candidate.entity_type, candidate.start, candidate.end, candidate.text)
        existing = unique.get(key)
        if existing is None or candidate.score > existing.score:
            unique[key] = candidate

    ordered = sorted(
        unique.values(),
        key=lambda item: (item.start, -(item.end - item.start), -item.score, item.entity_type),
    )
    selected: list[DetectionCandidate] = []
    for candidate in ordered:
        if any(candidate.start < kept.end and candidate.end > kept.start for kept in selected):
            continue
        selected.append(candidate)
    return selected


class LocalDetectionEngine:
    def __init__(
        self,
        spacy_model: str = DEFAULT_SPACY_MODEL,
        enabled_entities: Sequence[str] = DEFAULT_ENABLED_ENTITIES,
    ) -> None:
        self.enabled_entities = tuple(dict.fromkeys(enabled_entities))
        self.registry = RecognizerRegistry()
        for recognizer in (
            EmailAddressRecognizer(),
            PhoneRecognizer(supported_regions=("US", "UK", "DE", "FE", "IL", "IN", "CA", "BR", "IT")),
            IbanRecognizer(),
            ItalianFiscalCodeRecognizer(),
        ):
            self.registry.add_recognizer(recognizer)

        self.warnings: list[str] = []
        self.nlp = None
        needs_spacy = bool(set(self.enabled_entities) & {"PERSON", "ORGANIZATION"})
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError as exc:
            if needs_spacy:
                raise DetectionUnavailableError(
                    f"spaCy model '{spacy_model}' is required for PERSON/ORGANIZATION detection. "
                    "Install it locally before running Persona."
                ) from exc
            self.warnings.append(
                f"spaCy model '{spacy_model}' not available; continuing with regex recognizers only."
            )

    def analyze_segments(self, segments: Sequence[TextSegment]) -> list[DetectionMatch]:
        matches: list[DetectionMatch] = []
        counter = 1
        for segment in segments:
            for candidate in self._analyze_segment(segment):
                matches.append(
                    DetectionMatch(
                        match_id=f"m{counter:04d}",
                        segment_id=segment.segment_id,
                        location=segment.location,
                        entity_type=candidate.entity_type,
                        original_value=candidate.text,
                        start=candidate.start,
                        end=candidate.end,
                        score=candidate.score,
                        context=build_context(segment.text, candidate.start, candidate.end),
                    )
                )
                counter += 1
        return matches

    def _analyze_segment(self, segment: TextSegment) -> list[DetectionCandidate]:
        entities = list(self.enabled_entities)
        recognizers = self.registry.get_recognizers(language="en", all_fields=True)
        candidates: list[DetectionCandidate] = []
        for recognizer in recognizers:
            results: list[RecognizerResult] = recognizer.analyze(text=segment.text, entities=entities, nlp_artifacts=None)
            for result in results:
                text = segment.text[result.start : result.end]
                candidates.append(
                    DetectionCandidate(
                        entity_type=result.entity_type,
                        start=result.start,
                        end=result.end,
                        score=result.score,
                        text=text,
                    )
                )

        if self.nlp is not None:
            doc = self.nlp(segment.text)
            for ent in doc.ents:
                mapped_label = SPACY_LABEL_MAP.get(ent.label_)
                if mapped_label and mapped_label in self.enabled_entities:
                    candidates.append(
                        DetectionCandidate(
                            entity_type=mapped_label,
                            start=ent.start_char,
                            end=ent.end_char,
                            score=0.8,
                            text=ent.text,
                        )
                    )

        return _deduplicate_candidates(candidates)
