from __future__ import annotations

from pathlib import Path

import pytest
import spacy

from persona.core.detection import LocalDetectionEngine, parse_enabled_entities
from persona.exceptions import DetectionUnavailableError
from persona.models.entities import TextSegment


def _build_test_model(tmp_path: Path) -> Path:
    model_path = tmp_path / "test_spacy_model"
    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(
        [
            {"label": "PERSON", "pattern": "Mario Rossi"},
            {"label": "ORG", "pattern": "Urgewalt"},
        ]
    )
    nlp.to_disk(model_path)
    return model_path


def test_parse_enabled_entities() -> None:
    assert parse_enabled_entities(None) == ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER")
    assert parse_enabled_entities("person,email_address, iban ") == ("PERSON", "EMAIL_ADDRESS", "IBAN")


def test_local_detection_engine_detects_person_email_phone_and_optional_entities(tmp_path: Path) -> None:
    model_path = _build_test_model(tmp_path)
    detector = LocalDetectionEngine(
        spacy_model=str(model_path),
        enabled_entities=("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN", "IT_FISCAL_CODE", "ORGANIZATION"),
    )
    segments = [
        TextSegment(
            segment_id="seg-1",
            location="body/p0",
            container_type="paragraph",
            text=(
                "Mario Rossi can be reached at mario.rossi@example.com or +39 333 123 4567. "
                "Company: Urgewalt. IBAN IT60X0542811101000000123456 and RSSMRA85M01H501Z."
            ),
        )
    ]

    matches = detector.analyze_segments(segments)
    values = {(match.entity_type, match.original_value) for match in matches}

    assert ("PERSON", "Mario Rossi") in values
    assert ("EMAIL_ADDRESS", "mario.rossi@example.com") in values
    assert ("PHONE_NUMBER", "+39 333 123 4567") in values
    assert ("ORGANIZATION", "Urgewalt") in values
    assert ("IBAN", "IT60X0542811101000000123456") in values
    assert ("IT_FISCAL_CODE", "RSSMRA85M01H501Z") in values


def test_missing_spacy_model_raises_when_person_requested() -> None:
    with pytest.raises(DetectionUnavailableError):
        LocalDetectionEngine(spacy_model="missing_model_12345", enabled_entities=("PERSON",))


def test_missing_spacy_model_is_allowed_for_regex_only() -> None:
    detector = LocalDetectionEngine(
        spacy_model="missing_model_12345",
        enabled_entities=("EMAIL_ADDRESS", "PHONE_NUMBER"),
    )
    matches = detector.analyze_segments(
        [
            TextSegment(
                segment_id="seg-1",
                location="body/p0",
                container_type="paragraph",
                text="Write to alice@example.com or call +1 202 555 0101.",
            )
        ]
    )
    values = {(match.entity_type, match.original_value) for match in matches}
    assert ("EMAIL_ADDRESS", "alice@example.com") in values
    assert ("PHONE_NUMBER", "+1 202 555 0101") in values
    assert detector.warnings
