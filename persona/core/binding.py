from __future__ import annotations

from dataclasses import dataclass, field

from persona.models.entities import BindingCheck, BindingMetadata, FileFingerprint, RestoreIssue

PRAGMATIC_BINDING_MODE = "pragmatic"
STRICT_BINDING_MODE = "strict"
SUPPORTED_BINDING_MODES = (PRAGMATIC_BINDING_MODE, STRICT_BINDING_MODE)


@dataclass(slots=True)
class BindingAssessment:
    mode: str
    status: str
    checks: list[BindingCheck] = field(default_factory=list)
    issues: list[RestoreIssue] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return self.status == "refused"


def evaluate_document_binding(
    current: FileFingerprint,
    binding: BindingMetadata | None,
    *,
    mode: str,
) -> BindingAssessment:
    assessment = BindingAssessment(mode=mode, status="bound")

    if binding is None:
        assessment.checks.append(
            BindingCheck(
                code="BINDING_METADATA_PRESENT",
                status="missing",
                detail="Encrypted map does not contain document binding metadata.",
            )
        )
        assessment.issues.append(
            RestoreIssue(
                code="LEGACY_BINDING_METADATA_MISSING",
                message="Encrypted map does not contain document binding metadata. Compatibility fallback is in use.",
            )
        )
        if mode == STRICT_BINDING_MODE:
            assessment.status = "refused"
            assessment.issues.append(
                RestoreIssue(
                    code="STRICT_BINDING_REFUSED",
                    message="Strict binding mode requires document binding metadata, but the map is legacy.",
                )
            )
        else:
            assessment.status = "weak"
        return assessment

    _add_check(
        assessment,
        "FILE_FORMAT_MATCH",
        current.file_format == binding.censored.file_format,
        f"Expected format {binding.censored.file_format}, got {current.file_format}.",
        issue_code="FILE_FORMAT_MISMATCH",
        issue_message=f"Provided censored file format {current.file_format} does not match map format {binding.censored.file_format}.",
    )
    _add_check(
        assessment,
        "CENSORED_FILE_FINGERPRINT_MATCH",
        current.file_sha256 == binding.censored.file_sha256,
        "Exact file hash differs from the hash recorded when Persona generated the censored file.",
        issue_code="FILE_FINGERPRINT_MISMATCH",
        issue_message="Provided censored file bytes do not exactly match the file recorded in the map.",
    )
    _add_check(
        assessment,
        "CENSORED_LOGICAL_FINGERPRINT_MATCH",
        current.logical_sha256 == binding.censored.logical_sha256,
        "Logical content fingerprint differs from the recorded censored document.",
        issue_code="LOGICAL_FINGERPRINT_MISMATCH",
        issue_message="Provided censored file logical content differs from the content recorded in the map.",
    )
    _add_check(
        assessment,
        "CENSORED_STRUCTURE_FINGERPRINT_MATCH",
        current.structure_sha256 == binding.censored.structure_sha256,
        "Segment structure fingerprint differs from the recorded censored document.",
        issue_code="STRUCTURE_FINGERPRINT_MISMATCH",
        issue_message="Provided censored file structure differs from the structure recorded in the map.",
    )
    _add_check(
        assessment,
        "CENSORED_SEGMENT_COUNT_MATCH",
        current.segment_count == binding.censored.segment_count,
        f"Expected {binding.censored.segment_count} segments, got {current.segment_count}.",
        issue_code="SEGMENT_COUNT_MISMATCH",
        issue_message=(
            f"Provided censored file has {current.segment_count} segments, expected {binding.censored.segment_count}."
        ),
    )

    strong_match = (
        current.file_format == binding.censored.file_format
        and current.logical_sha256 == binding.censored.logical_sha256
        and current.structure_sha256 == binding.censored.structure_sha256
        and current.segment_count == binding.censored.segment_count
    )
    exact_file_match = current.file_sha256 == binding.censored.file_sha256

    if strong_match:
        assessment.status = "bound"
        return assessment

    assessment.issues.append(
        RestoreIssue(
            code="DOCUMENT_BINDING_WEAK",
            message="Document binding is weaker than expected for this map/file pair.",
        )
    )
    assessment.status = "weak"

    if mode == STRICT_BINDING_MODE:
        assessment.status = "refused"
        reason = "Strict binding mode requires matching format, logical fingerprint, structure fingerprint, and segment count."
        if exact_file_match:
            reason += " Exact file hash matched, but strong binding checks still failed."
        assessment.issues.append(
            RestoreIssue(
                code="STRICT_BINDING_REFUSED",
                message=reason,
            )
        )

    return assessment


def _add_check(
    assessment: BindingAssessment,
    code: str,
    passed: bool,
    detail: str,
    *,
    issue_code: str,
    issue_message: str,
) -> None:
    assessment.checks.append(BindingCheck(code=code, status="pass" if passed else "fail", detail=detail))
    if not passed:
        assessment.issues.append(RestoreIssue(code=issue_code, message=issue_message))
