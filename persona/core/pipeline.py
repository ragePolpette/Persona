from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from persona.adapters.base import build_document_metadata, get_adapter_for_path
from persona.core.detection import LocalDetectionEngine
from persona.core.masking import deterministic_mask
from persona.core.placeholders import build_placeholder
from persona.core.tokens import stable_token_id
from persona.models.entities import AnonymizationResult, DetectionMatch, MapEntry, RestoreResult, TextReplacement
from persona.review.interactive import review_matches
from persona.security.keystore import ensure_root_key
from persona.security.map_store import decrypt_map_file, encrypt_map_file


def _default_censored_path(input_path: Path, out_dir: Path) -> Path:
    return out_dir / f"{input_path.stem}.censored{input_path.suffix}"


def _default_restored_path(input_path: Path, out_dir: Path) -> Path:
    return out_dir / f"{input_path.stem}.restored{input_path.suffix}"


def _default_map_path(input_path: Path, out_dir: Path) -> Path:
    return out_dir / f"{input_path.stem}.persona-map.json"


def prepare_matches(root_key: bytes, matches: Sequence[DetectionMatch]) -> list[DetectionMatch]:
    prepared: list[DetectionMatch] = []
    for match in matches:
        match.token_id = stable_token_id(root_key, match.entity_type, match.original_value)
        match.masked_value = deterministic_mask(root_key, match.entity_type, match.original_value)
        match.placeholder = build_placeholder(match.token_id, match.masked_value)
        prepared.append(match)
    return prepared


def anonymize_file(
    input_path: Path,
    password: str,
    out_dir: Path | None = None,
    review: bool = True,
    enabled_entities: Sequence[str] | None = None,
    report_json: Path | None = None,
    spacy_model: str = "en_core_web_sm",
    review_prompt=None,
    review_console=None,
) -> AnonymizationResult:
    adapter = get_adapter_for_path(input_path)
    target_dir = out_dir or input_path.parent
    segments = adapter.extract_segments(input_path)
    detector = LocalDetectionEngine(
        spacy_model=spacy_model,
        enabled_entities=tuple(enabled_entities) if enabled_entities else ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"),
    )
    root_key = ensure_root_key(password)
    matches = prepare_matches(root_key, detector.analyze_segments(segments))
    reviewed_matches = review_matches(matches, prompt=review_prompt or input, console=review_console) if review else matches
    approved_matches = [match for match in reviewed_matches if match.approved]

    replacements_by_segment: dict[str, list[TextReplacement]] = defaultdict(list)
    entries: list[MapEntry] = []
    for match in approved_matches:
        replacements_by_segment[match.segment_id].append(
            TextReplacement(
                start=match.start,
                end=match.end,
                replacement=match.placeholder,
                token_id=match.token_id,
                entity_type=match.entity_type,
                original_value=match.original_value,
                masked_value=match.masked_value,
                location=match.location,
                segment_id=match.segment_id,
            )
        )
        entries.append(
            MapEntry(
                token_id=match.token_id,
                entity_type=match.entity_type,
                original_value=match.original_value,
                masked_value=match.masked_value,
                placeholder=match.placeholder,
                location=match.location,
                segment_id=match.segment_id,
                start=match.start,
                end=match.end,
            )
        )

    output_path = _default_censored_path(input_path, target_dir)
    map_path = _default_map_path(input_path, target_dir)
    adapter.apply_replacements(input_path, output_path, replacements_by_segment)
    encrypt_map_file(map_path, password, build_document_metadata(input_path), entries)

    warnings = list(detector.warnings)
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(
            json.dumps(
                {
                    "input_file": str(input_path),
                    "output_file": str(output_path),
                    "map_file": str(map_path),
                    "approved_matches": len(approved_matches),
                    "rejected_matches": len(reviewed_matches) - len(approved_matches),
                    "warnings": warnings,
                    "matches": [
                        {
                            "match_id": match.match_id,
                            "entity_type": match.entity_type,
                            "location": match.location,
                            "original_value": match.original_value,
                            "masked_value": match.masked_value,
                            "placeholder": match.placeholder,
                            "approved": match.approved,
                        }
                        for match in reviewed_matches
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return AnonymizationResult(
        output_file=str(output_path),
        map_file=str(map_path),
        entries=entries,
        warnings=warnings,
    )


def restore_file(
    censored_path: Path,
    map_path: Path,
    password: str,
    out_dir: Path | None = None,
    report_json: Path | None = None,
) -> RestoreResult:
    adapter = get_adapter_for_path(censored_path)
    target_dir = out_dir or censored_path.parent
    output_path = _default_restored_path(censored_path, target_dir)
    document, entries = decrypt_map_file(map_path, password)
    restored_count, warnings = adapter.restore_file(censored_path, output_path, entries)

    if document.file_format != censored_path.suffix.lower():
        warnings.append(
            f"Map format {document.file_format} does not match censored file suffix {censored_path.suffix.lower()}."
        )

    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(
            json.dumps(
                {
                    "input_file": str(censored_path),
                    "output_file": str(output_path),
                    "restored_count": restored_count,
                    "warnings": warnings,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return RestoreResult(
        output_file=str(output_path),
        restored_count=restored_count,
        warnings=warnings,
    )

