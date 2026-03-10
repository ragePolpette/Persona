from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from persona.adapters.base import build_document_metadata, build_file_fingerprint, get_adapter_for_path
from persona.core.binding import (
    PRAGMATIC_BINDING_MODE,
    STRICT_BINDING_MODE,
    SUPPORTED_BINDING_MODES,
    evaluate_document_binding,
)
from persona.core.detection import LocalDetectionEngine
from persona.core.masking import deterministic_mask
from persona.core.placeholders import build_placeholder, compute_placeholder_integrity_tag
from persona.core.tokens import stable_token_id
from persona.models.entities import (
    AnonymizationResult,
    BindingMetadata,
    DetectionMatch,
    MapEntry,
    RestoreResult,
    RestoreIssue,
    RestoreStats,
    TextReplacement,
)
from persona.review.interactive import review_matches
from persona.security.keystore import ensure_root_key, load_root_key
from persona.security.map_store import decrypt_map_file, encrypt_map_file
from persona.exceptions import InputValidationError, StrictBindingFailureError


@dataclass(slots=True)
class OutputPlan:
    output_file: Path
    map_file: Path | None = None


@dataclass(slots=True)
class ReplacementPlan:
    replacements_by_segment: dict[str, list[TextReplacement]]
    entries: list[MapEntry]


def _default_censored_path(input_path: Path, out_dir: Path) -> Path:
    return out_dir / f"{input_path.stem}.censored{input_path.suffix}"


def _default_restored_path(input_path: Path, out_dir: Path) -> Path:
    return out_dir / f"{input_path.stem}.restored{input_path.suffix}"


def _default_map_path(input_path: Path, out_dir: Path) -> Path:
    return out_dir / f"{input_path.stem}.persona-map.json"


def plan_anonymize_outputs(input_path: Path, out_dir: Path | None) -> OutputPlan:
    target_dir = out_dir or input_path.parent
    return OutputPlan(
        output_file=_default_censored_path(input_path, target_dir),
        map_file=_default_map_path(input_path, target_dir),
    )


def plan_restore_outputs(censored_path: Path, out_dir: Path | None) -> OutputPlan:
    target_dir = out_dir or censored_path.parent
    return OutputPlan(output_file=_default_restored_path(censored_path, target_dir))


def prepare_matches(root_key: bytes, matches: Sequence[DetectionMatch]) -> list[DetectionMatch]:
    prepared: list[DetectionMatch] = []
    for match in matches:
        if not match.token_id:
            match.token_id = stable_token_id(root_key, match.entity_type, match.original_value)
        if not match.masked_value:
            match.masked_value = deterministic_mask(root_key, match.entity_type, match.original_value)
        integrity_tag = compute_placeholder_integrity_tag(root_key, match.token_id, match.masked_value)
        match.placeholder = build_placeholder(match.token_id, match.masked_value, integrity_tag=integrity_tag)
        prepared.append(match)
    return prepared


def build_replacement_plan(matches: Sequence[DetectionMatch]) -> ReplacementPlan:
    replacements_by_segment: dict[str, list[TextReplacement]] = defaultdict(list)
    entries: list[MapEntry] = []
    for match in matches:
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
                score=match.score,
                reason=match.reason,
                metadata=dict(match.metadata),
            )
        )
    return ReplacementPlan(replacements_by_segment=replacements_by_segment, entries=entries)


def build_anonymize_report_payload(
    input_path: Path,
    output_plan: OutputPlan,
    reviewed_matches: Sequence[DetectionMatch],
    approved_matches: Sequence[DetectionMatch],
    warnings: Sequence[str],
) -> dict[str, object]:
    return {
        "input_file": str(input_path),
        "output_file": str(output_plan.output_file),
        "map_file": str(output_plan.map_file) if output_plan.map_file else None,
        "approved_matches": len(approved_matches),
        "rejected_matches": len(reviewed_matches) - len(approved_matches),
        "warnings": list(warnings),
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
    }


def build_restore_report_payload(
    censored_path: Path,
    output_plan: OutputPlan,
    stats: RestoreStats,
    *,
    binding_mode: str,
    binding_status: str,
    binding_checks,
) -> dict[str, object]:
    return {
        "input_file": str(censored_path),
        "output_file": str(output_plan.output_file),
        "binding_mode": binding_mode,
        "binding_status": binding_status,
        "binding_checks": [
            {
                "code": check.code,
                "status": check.status,
                "detail": check.detail,
            }
            for check in binding_checks
        ],
        "restored_count": stats.restored_count,
        "untouched_invalid_count": stats.untouched_invalid_count,
        "missing_expected_count": stats.missing_expected_count,
        "warnings": stats.warnings,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "location": issue.location,
                "segment_id": issue.segment_id,
                "token_id": issue.token_id,
                "placeholder": issue.placeholder,
            }
            for issue in stats.issues
        ],
    }


def write_json_report(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
    output_plan = plan_anonymize_outputs(input_path, out_dir)
    segments = adapter.extract_segments(input_path)
    detector = LocalDetectionEngine(
        spacy_model=spacy_model,
        enabled_entities=tuple(enabled_entities) if enabled_entities else ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"),
    )
    root_key = ensure_root_key(password)
    original_fingerprint = build_file_fingerprint(input_path, segments)
    matches = prepare_matches(root_key, detector.analyze_segments(segments))
    reviewed_matches = review_matches(matches, prompt=review_prompt or input, console=review_console) if review else matches
    reviewed_matches = prepare_matches(root_key, reviewed_matches)
    approved_matches = [match for match in reviewed_matches if match.approved]
    plan = build_replacement_plan(approved_matches)

    adapter.apply_replacements(input_path, output_plan.output_file, plan.replacements_by_segment)
    censored_segments = adapter.extract_segments(output_plan.output_file)
    censored_fingerprint = build_file_fingerprint(output_plan.output_file, censored_segments)
    binding = BindingMetadata(
        version=1,
        original=original_fingerprint,
        censored=censored_fingerprint,
        entry_count=len(plan.entries),
    )
    assert output_plan.map_file is not None
    encrypt_map_file(
        output_plan.map_file,
        password,
        build_document_metadata(input_path),
        plan.entries,
        binding=binding,
    )

    warnings = list(detector.warnings)
    write_json_report(
        report_json,
        build_anonymize_report_payload(input_path, output_plan, reviewed_matches, approved_matches, warnings),
    )

    return AnonymizationResult(
        output_file=str(output_plan.output_file),
        map_file=str(output_plan.map_file),
        entries=plan.entries,
        warnings=warnings,
    )


def restore_file(
    censored_path: Path,
    map_path: Path,
    password: str,
    out_dir: Path | None = None,
    report_json: Path | None = None,
    binding_mode: str = PRAGMATIC_BINDING_MODE,
) -> RestoreResult:
    if binding_mode not in SUPPORTED_BINDING_MODES:
        raise InputValidationError(f"Unsupported binding mode '{binding_mode}'.")
    adapter = get_adapter_for_path(censored_path)
    output_plan = plan_restore_outputs(censored_path, out_dir)
    _document, entries, binding = decrypt_map_file(map_path, password)
    current_segments = adapter.extract_segments(censored_path)
    current_fingerprint = build_file_fingerprint(censored_path, current_segments)
    binding_assessment = evaluate_document_binding(current_fingerprint, binding, mode=binding_mode)

    if binding_assessment.refused:
        write_json_report(
            report_json,
            build_restore_report_payload(
                censored_path,
                output_plan,
                RestoreStats(issues=binding_assessment.issues),
                binding_mode=binding_mode,
                binding_status=binding_assessment.status,
                binding_checks=binding_assessment.checks,
            ),
        )
        raise StrictBindingFailureError("Strict binding checks refused restore for this file/map pair.")

    root_key = load_root_key(password)
    stats = adapter.restore_file(censored_path, output_plan.output_file, entries, root_key=root_key)
    stats.issues.extend(binding_assessment.issues)

    write_json_report(
        report_json,
        build_restore_report_payload(
            censored_path,
            output_plan,
            stats,
            binding_mode=binding_mode,
            binding_status=binding_assessment.status,
            binding_checks=binding_assessment.checks,
        ),
    )

    return RestoreResult(
        output_file=str(output_plan.output_file),
        restored_count=stats.restored_count,
        untouched_invalid_count=stats.untouched_invalid_count,
        missing_expected_count=stats.missing_expected_count,
        binding_mode=binding_mode,
        binding_status=binding_assessment.status,
        binding_checks=binding_assessment.checks,
        issues=stats.issues,
        warnings=stats.warnings,
    )
