from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from persona.adapters.base import build_document_metadata, build_file_fingerprint, get_adapter_for_path
from persona.core.binding import PRAGMATIC_BINDING_MODE
from persona.core.pipeline import (
    build_anonymize_report_payload,
    build_replacement_plan,
    plan_anonymize_outputs,
    prepare_matches,
    write_json_report,
)
from persona.engine.analysis import BlockAnalysisOptions, analyze_segments_with_backend
from persona.engine.llm import LLMBackendConfig, LocalLLMBackend, build_backend
from persona.models.entities import AnonymizationResult, BindingMetadata, DetectionMatch, RestoreResult, TextSegment
from persona.review.interactive import review_matches
from persona.security.keystore import ensure_root_key
from persona.security.map_store import encrypt_map_file


@dataclass(slots=True)
class DocumentSession:
    input_path: Path
    segments: list[TextSegment]
    matches: list[DetectionMatch]
    warnings: list[str]


def segments_to_preview_text(segments: Sequence[TextSegment]) -> str:
    rendered: list[str] = []
    for segment in segments:
        if segment.text:
            rendered.append(f"[{segment.location}]\n{segment.text}")
    return "\n\n".join(rendered)


class PersonaEngine:
    def __init__(
        self,
        *,
        backend_config: LLMBackendConfig | None = None,
        backend: LocalLLMBackend | None = None,
        analysis_options: BlockAnalysisOptions | None = None,
    ) -> None:
        self.backend_config = backend_config or LLMBackendConfig.from_env()
        self.backend = backend or build_backend(self.backend_config)
        self.analysis_options = analysis_options or BlockAnalysisOptions()

    def analyze_document(self, input_path: Path, password: str) -> DocumentSession:
        adapter = get_adapter_for_path(input_path)
        segments = adapter.extract_segments(input_path)
        root_key = ensure_root_key(password)
        matches = analyze_segments_with_backend(segments, self.backend, options=self.analysis_options)
        prepared_matches = prepare_matches(root_key, matches)
        return DocumentSession(input_path=input_path, segments=segments, matches=prepared_matches, warnings=[])

    def anonymize_document(
        self,
        input_path: Path,
        password: str,
        *,
        out_dir: Path | None = None,
        review: bool = True,
        report_json: Path | None = None,
        review_prompt=None,
        review_console=None,
    ) -> AnonymizationResult:
        session = self.analyze_document(input_path, password)
        reviewed_matches = (
            review_matches(session.matches, prompt=review_prompt or input, console=review_console)
            if review
            else session.matches
        )
        return self.anonymize_with_matches(
            input_path,
            password,
            reviewed_matches,
            out_dir=out_dir,
            report_json=report_json,
            warnings=session.warnings,
        )

    def anonymize_with_matches(
        self,
        input_path: Path,
        password: str,
        matches: Sequence[DetectionMatch],
        *,
        out_dir: Path | None = None,
        report_json: Path | None = None,
        warnings: Sequence[str] | None = None,
    ) -> AnonymizationResult:
        adapter = get_adapter_for_path(input_path)
        output_plan = plan_anonymize_outputs(input_path, out_dir)
        segments = adapter.extract_segments(input_path)
        root_key = ensure_root_key(password)
        reviewed_matches = prepare_matches(root_key, list(matches))
        approved_matches = [match for match in reviewed_matches if match.approved]
        plan = build_replacement_plan(approved_matches)

        adapter.apply_replacements(input_path, output_plan.output_file, plan.replacements_by_segment)
        censored_segments = adapter.extract_segments(output_plan.output_file)
        binding = BindingMetadata(
            version=1,
            original=build_file_fingerprint(input_path, segments),
            censored=build_file_fingerprint(output_plan.output_file, censored_segments),
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

        report_payload = build_anonymize_report_payload(
            input_path,
            output_plan,
            reviewed_matches,
            approved_matches,
            list(warnings or []),
        )
        report_payload["backend"] = self.backend.name
        report_payload["preview_original"] = segments_to_preview_text(segments)
        report_payload["preview_censored"] = segments_to_preview_text(censored_segments)
        report_payload["matches"] = [
            item
            | {
                "score": match.score,
                "reason": match.reason,
                "metadata": dict(match.metadata),
            }
            for item, match in zip(report_payload["matches"], reviewed_matches, strict=True)
        ]
        write_json_report(report_json, report_payload)

        return AnonymizationResult(
            output_file=str(output_plan.output_file),
            map_file=str(output_plan.map_file),
            entries=plan.entries,
            warnings=list(warnings or []),
        )

    def restore_document(
        self,
        censored_path: Path,
        map_path: Path,
        password: str,
        *,
        out_dir: Path | None = None,
        report_json: Path | None = None,
        binding_mode: str = PRAGMATIC_BINDING_MODE,
    ) -> RestoreResult:
        from persona.core.pipeline import restore_file

        return restore_file(
            censored_path=censored_path,
            map_path=map_path,
            password=password,
            out_dir=out_dir,
            report_json=report_json,
            binding_mode=binding_mode,
        )
