from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from persona.engine.chunking import iter_text_chunks
from persona.engine.llm import LocalLLMBackend
from persona.models.entities import DetectionMatch, TextSegment


@dataclass(slots=True)
class BlockAnalysisOptions:
    max_chunk_chars: int = 1200
    chunk_overlap: int = 120


def _build_context(text: str, start: int, end: int, radius: int = 36) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return f"{text[left:start]}[{text[start:end]}]{text[end:right]}"


def _resolve_overlaps(matches: list[DetectionMatch]) -> list[DetectionMatch]:
    ordered = sorted(matches, key=lambda item: (item.start, -(item.end - item.start), -(item.score or 0.0)))
    resolved: list[DetectionMatch] = []
    for match in ordered:
        if any(match.start < kept.end and match.end > kept.start for kept in resolved):
            continue
        resolved.append(match)
    return sorted(resolved, key=lambda item: (item.location, item.start, item.end))


def analyze_segments_with_backend(
    segments: Sequence[TextSegment],
    backend: LocalLLMBackend,
    *,
    options: BlockAnalysisOptions | None = None,
) -> list[DetectionMatch]:
    analysis_options = options or BlockAnalysisOptions()
    matches: list[DetectionMatch] = []
    counter = 1
    for segment in segments:
        segment_matches: list[DetectionMatch] = []
        for chunk in iter_text_chunks(
            segment.text,
            max_chars=analysis_options.max_chunk_chars,
            overlap=analysis_options.chunk_overlap,
        ):
            findings = backend.analyze_chunk(chunk.text)
            for finding in findings:
                start = chunk.start + finding.start
                end = chunk.start + finding.end
                original_value = segment.text[start:end]
                segment_matches.append(
                    DetectionMatch(
                        match_id=f"m{counter:04d}",
                        segment_id=segment.segment_id,
                        location=segment.location,
                        entity_type=(finding.label or "SENSITIVE_BLOCK").strip() or "SENSITIVE_BLOCK",
                        original_value=original_value,
                        start=start,
                        end=end,
                        score=finding.confidence or 0.0,
                        context=_build_context(segment.text, start, end),
                        reason=finding.reason or "",
                        metadata={"chunk_index": chunk.index},
                    )
                )
                counter += 1
        matches.extend(_resolve_overlaps(segment_matches))
    return matches
