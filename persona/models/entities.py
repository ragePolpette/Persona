from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class DocumentMetadata:
    source_name: str
    source_path: str
    file_format: str
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TextSegment:
    segment_id: str
    location: str
    text: str
    container_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DetectionMatch:
    match_id: str
    segment_id: str
    location: str
    entity_type: str
    original_value: str
    start: int
    end: int
    score: float
    context: str
    token_id: str = ""
    masked_value: str = ""
    placeholder: str = ""
    approved: bool = True


@dataclass(slots=True)
class MapEntry:
    token_id: str
    entity_type: str
    original_value: str
    masked_value: str
    placeholder: str
    location: str
    segment_id: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MapEntry":
        return cls(**payload)


@dataclass(slots=True)
class TextReplacement:
    start: int
    end: int
    replacement: str
    token_id: str
    entity_type: str
    original_value: str
    masked_value: str
    location: str
    segment_id: str


@dataclass(slots=True)
class AnonymizationResult:
    output_file: str
    map_file: str
    entries: list[MapEntry]
    warnings: list[str]


@dataclass(slots=True)
class RestoreResult:
    output_file: str
    restored_count: int
    warnings: list[str]

