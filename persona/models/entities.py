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
class FileFingerprint:
    file_name: str
    file_stem: str
    file_format: str
    file_sha256: str
    logical_sha256: str
    structure_sha256: str
    segment_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FileFingerprint":
        return cls(**payload)


@dataclass(slots=True)
class BindingMetadata:
    version: int
    original: FileFingerprint
    censored: FileFingerprint
    entry_count: int
    marker_support: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "original": self.original.to_dict(),
            "censored": self.censored.to_dict(),
            "entry_count": self.entry_count,
            "marker_support": self.marker_support,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BindingMetadata":
        return cls(
            version=payload["version"],
            original=FileFingerprint.from_dict(payload["original"]),
            censored=FileFingerprint.from_dict(payload["censored"]),
            entry_count=payload["entry_count"],
            marker_support=payload.get("marker_support", "none"),
        )


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
    untouched_invalid_count: int
    missing_expected_count: int
    binding_mode: str
    binding_status: str
    binding_checks: list["BindingCheck"]
    issues: list["RestoreIssue"]
    warnings: list[str]

    @property
    def has_integrity_issues(self) -> bool:
        return (
            self.untouched_invalid_count > 0
            or self.missing_expected_count > 0
            or self.binding_status != "bound"
            or bool(self.issues)
        )


@dataclass(slots=True)
class RestoreIssue:
    code: str
    message: str
    location: str = ""
    segment_id: str = ""
    token_id: str = ""
    placeholder: str = ""


@dataclass(slots=True)
class BindingCheck:
    code: str
    status: str
    detail: str


@dataclass(slots=True)
class RestoreStats:
    restored_count: int = 0
    untouched_invalid_count: int = 0
    missing_expected_count: int = 0
    issues: list[RestoreIssue] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [issue.message for issue in self.issues]

    def extend(self, other: "RestoreStats") -> None:
        self.restored_count += other.restored_count
        self.untouched_invalid_count += other.untouched_invalid_count
        self.missing_expected_count += other.missing_expected_count
        self.issues.extend(other.issues)


@dataclass(slots=True)
class TextRestoreOutcome:
    text: str
    stats: RestoreStats
