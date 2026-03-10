from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any, Callable, Protocol
from urllib import error, request

from persona.config import (
    DEFAULT_LLM_BACKEND,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_CLI,
    DEFAULT_LLM_MODEL,
)
from persona.exceptions import InputValidationError, LLMBackendError, LLMOutputValidationError

SUPPORTED_BACKENDS = ("mock", "qwen-ollama", "qwen-llama-cpp")


@dataclass(slots=True)
class LLMBlockFinding:
    start: int
    end: int
    text: str
    confidence: float | None = None
    label: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class LLMBackendConfig:
    backend: str = DEFAULT_LLM_BACKEND
    model_ref: str = DEFAULT_LLM_MODEL
    base_url: str = DEFAULT_LLM_BASE_URL
    cli_path: str = DEFAULT_LLM_CLI
    model_path: str = ""
    timeout_seconds: int = 60
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> "LLMBackendConfig":
        extra_args = tuple(
            arg.strip()
            for arg in os.environ.get("PERSONA_LLM_EXTRA_ARGS", "").split("::")
            if arg.strip()
        )
        timeout_value = os.environ.get("PERSONA_LLM_TIMEOUT", "60").strip() or "60"
        return cls(
            backend=os.environ.get("PERSONA_LLM_BACKEND", DEFAULT_LLM_BACKEND).strip().lower(),
            model_ref=os.environ.get("PERSONA_LLM_MODEL", DEFAULT_LLM_MODEL).strip(),
            base_url=os.environ.get("PERSONA_LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip(),
            cli_path=os.environ.get("PERSONA_LLM_CLI", DEFAULT_LLM_CLI).strip(),
            model_path=os.environ.get("PERSONA_LLM_MODEL_PATH", "").strip(),
            timeout_seconds=int(timeout_value),
            extra_args=extra_args,
        )


class LocalLLMBackend(Protocol):
    name: str

    def analyze_chunk(self, text: str) -> list[LLMBlockFinding]:
        raise NotImplementedError


def build_detection_prompt(text: str) -> str:
    return (
        "You are a local offline anonymization assistant.\n"
        "Analyze the provided text chunk and identify only logically sensitive text spans that should be masked before sharing the document.\n"
        "Return JSON only.\n"
        "Do not rewrite the text.\n"
        "Do not add prose.\n"
        "Output format:\n"
        "{\n"
        '  "findings": [\n'
        '    {"start": 0, "end": 5, "text": "Alice", "confidence": 0.95, "label": "person", "reason": "personal name"}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- return only spans that appear exactly in the chunk\n"
        "- prefer larger logical blocks over tiny fragments\n"
        '- if nothing should be anonymized, return {"findings": []}\n'
        "\n"
        f"TEXT CHUNK:\n{text}"
    )


def _extract_json_fragment(raw_output: str) -> str:
    stripped = raw_output.strip()
    if not stripped:
        raise LLMOutputValidationError("Local LLM returned an empty response.")

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return stripped[start : index + 1]
    raise LLMOutputValidationError("Local LLM response did not contain valid JSON.")


def _normalize_label(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise LLMOutputValidationError("Local LLM returned a non-numeric confidence value.") from exc


def _validate_finding(item: dict[str, Any], text: str) -> LLMBlockFinding:
    if "text" not in item and ("start" not in item or "end" not in item):
        raise LLMOutputValidationError("Each finding must contain either text or start/end offsets.")

    if "start" in item and "end" in item:
        try:
            start = int(item["start"])
            end = int(item["end"])
        except (TypeError, ValueError) as exc:
            raise LLMOutputValidationError("Local LLM returned non-integer offsets.") from exc
        if start < 0 or end <= start or end > len(text):
            raise LLMOutputValidationError("Local LLM returned out-of-range offsets.")
        expected_text = text[start:end]
        finding_text = str(item.get("text", expected_text))
        if finding_text != expected_text:
            raise LLMOutputValidationError("Finding text does not match the supplied offsets.")
    else:
        finding_text = str(item["text"])
        start = text.find(finding_text)
        if start == -1:
            raise LLMOutputValidationError("Finding text was not found in the analyzed chunk.")
        if text.find(finding_text, start + 1) != -1:
            raise LLMOutputValidationError(
                "Finding text was ambiguous in the analyzed chunk and offsets were not provided."
            )
        end = start + len(finding_text)

    return LLMBlockFinding(
        start=start,
        end=end,
        text=text[start:end],
        confidence=_coerce_float(item.get("confidence")),
        label=_normalize_label(item.get("label")),
        reason=_normalize_label(item.get("reason")),
    )


def parse_backend_response(raw_output: str, text: str) -> list[LLMBlockFinding]:
    try:
        payload = json.loads(_extract_json_fragment(raw_output))
    except JSONDecodeError as exc:
        raise LLMOutputValidationError("Local LLM returned malformed JSON.") from exc

    findings_payload = payload.get("findings") if isinstance(payload, dict) else payload
    if not isinstance(findings_payload, list):
        raise LLMOutputValidationError("Local LLM JSON must contain a findings array.")

    findings = [_validate_finding(item, text) for item in findings_payload if isinstance(item, dict)]
    findings.sort(key=lambda item: (item.start, item.end))
    return findings


class MockLLMBackend:
    name = "mock"

    def __init__(
        self,
        response_factory: Callable[[str], list[LLMBlockFinding]] | None = None,
        static_findings: list[LLMBlockFinding] | None = None,
    ) -> None:
        self._response_factory = response_factory
        self._static_findings = static_findings or []

    def analyze_chunk(self, text: str) -> list[LLMBlockFinding]:
        if self._response_factory is not None:
            return list(self._response_factory(text))
        return list(self._static_findings)


class QwenOllamaBackend:
    name = "qwen-ollama"

    def __init__(self, config: LLMBackendConfig) -> None:
        self.config = config

    def analyze_chunk(self, text: str) -> list[LLMBlockFinding]:
        prompt = build_detection_prompt(text)
        body = json.dumps(
            {
                "model": self.config.model_ref,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        req = request.Request(
            url=f"{self.config.base_url.rstrip('/')}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.URLError as exc:
            raise LLMBackendError(
                f"Unable to reach local Ollama backend at {self.config.base_url}. Configure Persona to use your local Qwen runtime."
            ) from exc
        try:
            payload = json.loads(raw)
            model_output = payload["response"]
        except (JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMBackendError("Local Ollama backend returned an unexpected response envelope.") from exc
        return parse_backend_response(model_output, text)


class QwenLlamaCppBackend:
    name = "qwen-llama-cpp"

    def __init__(self, config: LLMBackendConfig) -> None:
        self.config = config

    def analyze_chunk(self, text: str) -> list[LLMBlockFinding]:
        if not self.config.model_path:
            raise InputValidationError("A local model path is required for the qwen-llama-cpp backend.")
        prompt = build_detection_prompt(text)
        command = [
            self.config.cli_path,
            "-m",
            self.config.model_path,
            "-p",
            prompt,
            "--temp",
            "0",
        ]
        command.extend(self.config.extra_args)
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise LLMBackendError(
                f"Unable to execute local llama.cpp runtime '{self.config.cli_path}'."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMBackendError("Local llama.cpp runtime timed out while analyzing a chunk.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "unknown runtime failure"
            raise LLMBackendError(f"Local llama.cpp runtime failed: {stderr}") from exc
        return parse_backend_response(completed.stdout, text)


def build_backend(
    config: LLMBackendConfig,
    *,
    mock_backend: MockLLMBackend | None = None,
) -> LocalLLMBackend:
    backend_name = config.backend.strip().lower()
    if backend_name not in SUPPORTED_BACKENDS:
        raise InputValidationError(
            f"Unsupported local LLM backend '{config.backend}'. Supported backends: {', '.join(SUPPORTED_BACKENDS)}."
        )
    if backend_name == "mock":
        return mock_backend or MockLLMBackend()
    if backend_name == "qwen-ollama":
        return QwenOllamaBackend(config)
    return QwenLlamaCppBackend(config)
