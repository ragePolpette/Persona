from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from persona.config import LOCAL_APP_DATA_DIR
from persona.exceptions import InputFileError, StorageError
from persona.models.entities import DetectionMatch


@dataclass(slots=True)
class StoredDocument:
    document_id: str
    original_name: str
    file_format: str
    created_at: str
    status: str
    original_path: str
    censored_path: str = ""
    map_path: str = ""
    restored_path: str = ""
    backend_name: str = ""
    matches: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StoredDocument":
        return cls(
            document_id=payload["document_id"],
            original_name=payload["original_name"],
            file_format=payload["file_format"],
            created_at=payload["created_at"],
            status=payload["status"],
            original_path=payload["original_path"],
            censored_path=payload.get("censored_path", ""),
            map_path=payload.get("map_path", ""),
            restored_path=payload.get("restored_path", ""),
            backend_name=payload.get("backend_name", ""),
            matches=list(payload.get("matches", [])),
            warnings=list(payload.get("warnings", [])),
        )

    def hydrated_matches(self) -> list[DetectionMatch]:
        return [DetectionMatch.from_dict(item) for item in self.matches]


class LocalDocumentStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or LOCAL_APP_DATA_DIR
        self.originals_dir = self.root_dir / "originals"
        self.censored_dir = self.root_dir / "censored"
        self.maps_dir = self.root_dir / "maps"
        self.metadata_dir = self.root_dir / "metadata"
        self.restored_dir = self.root_dir / "restored"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        for path in (
            self.root_dir,
            self.originals_dir,
            self.censored_dir,
            self.maps_dir,
            self.metadata_dir,
            self.restored_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def list_documents(self) -> list[StoredDocument]:
        records = [self.load_document(path.stem) for path in self.metadata_dir.glob("*.json")]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def create_document(self, source_path: Path, *, original_name: str | None = None) -> StoredDocument:
        if not source_path.exists():
            raise InputFileError(f"Input file not found: {source_path}")
        document_id = uuid.uuid4().hex[:12]
        target_path = self.originals_dir / f"{document_id}{source_path.suffix.lower()}"
        shutil.copy2(source_path, target_path)
        record = StoredDocument(
            document_id=document_id,
            original_name=original_name or source_path.name,
            file_format=source_path.suffix.lower(),
            created_at=datetime.now(UTC).isoformat(),
            status="uploaded",
            original_path=str(target_path),
        )
        self.save_document(record)
        return record

    def load_document(self, document_id: str) -> StoredDocument:
        path = self.metadata_dir / f"{document_id}.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise StorageError(f"Document metadata not found for id '{document_id}'.") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StorageError(f"Document metadata is corrupt for id '{document_id}'.") from exc
        return StoredDocument.from_dict(payload)

    def save_document(self, record: StoredDocument) -> None:
        path = self.metadata_dir / f"{record.document_id}.json"
        path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
