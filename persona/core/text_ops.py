from __future__ import annotations

from collections import Counter

from persona.core.placeholders import (
    ParsedPlaceholder,
    compute_placeholder_integrity_tag,
    scan_placeholder_candidates,
)
from persona.models.entities import MapEntry, RestoreIssue, RestoreStats, TextReplacement, TextRestoreOutcome


def apply_text_replacements(text: str, replacements: list[TextReplacement]) -> str:
    result = text
    ordered = sorted(replacements, key=lambda item: (item.start, item.end))
    for current, following in zip(ordered, ordered[1:]):
        if current.end > following.start:
            raise ValueError("Overlapping replacements are not allowed.")
    for replacement in sorted(replacements, key=lambda item: item.start, reverse=True):
        result = result[: replacement.start] + replacement.replacement + result[replacement.end :]
    return result


def _expected_placeholder_counts(entries: list[MapEntry]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for entry in entries:
        counts[entry.placeholder] += 1
    return counts


def _classify_token_mismatch(
    placeholder: ParsedPlaceholder,
    expected_entries: list[MapEntry],
    root_key: bytes | None,
) -> str:
    if placeholder.version == "P2" and root_key is not None:
        expected_tag = compute_placeholder_integrity_tag(
            root_key,
            placeholder.token_id,
            placeholder.masked_value,
        )
        if placeholder.integrity_tag != expected_tag:
            return "ALTERED_PLACEHOLDER"
        if not any(entry.masked_value == placeholder.masked_value for entry in expected_entries):
            return "UNEXPECTED_PLACEHOLDER"
        return "ALTERED_PLACEHOLDER"

    if any(entry.masked_value == placeholder.masked_value for entry in expected_entries):
        return "ALTERED_PLACEHOLDER"
    return "UNEXPECTED_PLACEHOLDER"


def strict_restore_text(
    text: str,
    entries: list[MapEntry],
    *,
    root_key: bytes | None = None,
    segment_id: str = "",
    location: str = "",
) -> TextRestoreOutcome:
    stats = RestoreStats()
    remaining_expected = _expected_placeholder_counts(entries)
    entries_by_token: dict[str, list[MapEntry]] = {}
    for entry in entries:
        entries_by_token.setdefault(entry.token_id, []).append(entry)

    replacements: list[TextReplacement] = []
    for candidate in scan_placeholder_candidates(text):
        if candidate.error:
            stats.untouched_invalid_count += 1
            stats.issues.append(
                RestoreIssue(
                    code="MALFORMED_PLACEHOLDER",
                    message=f"Malformed placeholder at offset {candidate.start}: {candidate.error}",
                    location=location,
                    segment_id=segment_id,
                    placeholder=candidate.raw_value,
                )
            )
            continue

        assert candidate.parsed is not None
        parsed = candidate.parsed
        expected_entries = entries_by_token.get(parsed.token_id, [])
        if not expected_entries:
            stats.untouched_invalid_count += 1
            stats.issues.append(
                RestoreIssue(
                    code="UNEXPECTED_PLACEHOLDER",
                    message=f"Unexpected placeholder at offset {candidate.start} for token {parsed.token_id}.",
                    location=location,
                    segment_id=segment_id,
                    token_id=parsed.token_id,
                    placeholder=parsed.raw_value,
                )
            )
            continue

        matching_entry = next((entry for entry in expected_entries if entry.placeholder == parsed.raw_value), None)
        if matching_entry is None:
            issue_code = _classify_token_mismatch(parsed, expected_entries, root_key)
            stats.untouched_invalid_count += 1
            stats.issues.append(
                RestoreIssue(
                    code=issue_code,
                    message=f"Placeholder at offset {candidate.start} for token {parsed.token_id} did not match the encrypted map entry.",
                    location=location,
                    segment_id=segment_id,
                    token_id=parsed.token_id,
                    placeholder=parsed.raw_value,
                )
            )
            continue

        if remaining_expected[matching_entry.placeholder] <= 0:
            stats.untouched_invalid_count += 1
            stats.issues.append(
                RestoreIssue(
                    code="DUPLICATE_PLACEHOLDER",
                    message=f"Duplicate placeholder at offset {candidate.start} for token {parsed.token_id} left untouched.",
                    location=location,
                    segment_id=segment_id,
                    token_id=parsed.token_id,
                    placeholder=parsed.raw_value,
                )
            )
            continue

        remaining_expected[matching_entry.placeholder] -= 1
        replacements.append(
            TextReplacement(
                start=candidate.start,
                end=candidate.end,
                replacement=matching_entry.original_value,
                token_id=matching_entry.token_id,
                entity_type=matching_entry.entity_type,
                original_value=matching_entry.original_value,
                masked_value=matching_entry.masked_value,
                location=matching_entry.location,
                segment_id=matching_entry.segment_id,
            )
        )

    for placeholder, missing_count in remaining_expected.items():
        if missing_count <= 0:
            continue
        sample_entry = next(entry for entry in entries if entry.placeholder == placeholder)
        stats.missing_expected_count += missing_count
        stats.issues.append(
            RestoreIssue(
                code="MISSING_EXPECTED_PLACEHOLDER",
                message=(
                    f"Expected {missing_count} placeholder occurrence(s) for token {sample_entry.token_id} "
                    "were not found in the censored content."
                ),
                location=location,
                segment_id=segment_id,
                token_id=sample_entry.token_id,
                placeholder=placeholder,
            )
        )

    restored_text = apply_text_replacements(text, replacements) if replacements else text
    stats.restored_count = len(replacements)
    return TextRestoreOutcome(text=restored_text, stats=stats)
