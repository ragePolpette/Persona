from __future__ import annotations

from collections import Counter, defaultdict

from persona.core.placeholders import scan_placeholders
from persona.models.entities import MapEntry, TextReplacement


def apply_text_replacements(text: str, replacements: list[TextReplacement]) -> str:
    result = text
    ordered = sorted(replacements, key=lambda item: (item.start, item.end))
    for current, following in zip(ordered, ordered[1:]):
        if current.end > following.start:
            raise ValueError("Overlapping replacements are not allowed.")
    for replacement in sorted(replacements, key=lambda item: item.start, reverse=True):
        result = result[: replacement.start] + replacement.replacement + result[replacement.end :]
    return result


def strict_restore_text(text: str, entries: list[MapEntry]) -> tuple[str, list[str], int]:
    warnings: list[str] = []
    expected_by_token: dict[str, set[str]] = defaultdict(set)
    placeholder_to_original: dict[str, str] = {}
    expected_counts: Counter[str] = Counter()
    placeholder_to_token: dict[str, str] = {}
    for entry in entries:
        expected_by_token[entry.token_id].add(entry.placeholder)
        placeholder_to_original[entry.placeholder] = entry.original_value
        placeholder_to_token[entry.placeholder] = entry.token_id
        expected_counts[entry.placeholder] += 1

    for placeholder in scan_placeholders(text):
        expected = expected_by_token.get(placeholder.token_id)
        if expected and placeholder.raw_value not in expected:
            warnings.append(
                f"Placeholder altered at offset {placeholder.start}: token {placeholder.token_id} left untouched."
            )

    for placeholder, expected_count in expected_counts.items():
        actual_count = text.count(placeholder)
        if actual_count < expected_count:
            warnings.append(
                f"Expected {expected_count} placeholder occurrence(s) for token "
                f"{placeholder_to_token[placeholder]}, found {actual_count}. Some placeholders were altered."
            )

    restored = text
    restored_count = 0
    for placeholder, original_value in sorted(placeholder_to_original.items(), key=lambda item: len(item[0]), reverse=True):
        occurrences = restored.count(placeholder)
        if occurrences:
            restored = restored.replace(placeholder, original_value)
            restored_count += occurrences
    return restored, warnings, restored_count
