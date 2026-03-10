from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Optional

import typer

from persona.core.binding import PRAGMATIC_BINDING_MODE, STRICT_BINDING_MODE, SUPPORTED_BINDING_MODES
from persona.exceptions import ExitCode, InputValidationError, PasswordResolutionError, PersonaError
from persona.engine.llm import LLMBackendConfig, SUPPORTED_BACKENDS
from persona.engine.service import PersonaEngine

app = typer.Typer(
    add_completion=False,
    help="Offline CLI for deterministic anonymization and strict restore of local documents.",
)


def _resolve_password(password_prompt: bool, password_env: Optional[str]) -> str:
    if password_env:
        value = os.environ.get(password_env)
        if value:
            return value
        raise PasswordResolutionError(f"Environment variable '{password_env}' is not set.")
    if password_prompt:
        return getpass.getpass("Persona password: ")
    return getpass.getpass("Persona password: ")


def _backend_config(
    backend: str,
    model_ref: Optional[str],
    base_url: Optional[str],
    cli_path: Optional[str],
    model_path: Optional[str],
) -> LLMBackendConfig:
    config = LLMBackendConfig.from_env()
    if backend:
        config.backend = backend.strip().lower()
    if config.backend not in SUPPORTED_BACKENDS:
        raise InputValidationError(
            f"Unsupported local LLM backend '{backend}'. Supported backends: {', '.join(SUPPORTED_BACKENDS)}."
        )
    if model_ref:
        config.model_ref = model_ref
    if base_url:
        config.base_url = base_url
    if cli_path:
        config.cli_path = cli_path
    if model_path:
        config.model_path = model_path
    return config


@app.command()
def anonymize(
    input_file: Path = typer.Argument(..., dir_okay=False),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", file_okay=False),
    review: bool = typer.Option(True, "--review/--no-review"),
    password_prompt: bool = typer.Option(False, "--password-prompt"),
    password_env: Optional[str] = typer.Option(None, "--password-env"),
    backend: str = typer.Option("qwen-ollama", "--backend"),
    model_ref: Optional[str] = typer.Option(None, "--model-ref"),
    base_url: Optional[str] = typer.Option(None, "--base-url"),
    cli_path: Optional[str] = typer.Option(None, "--cli-path"),
    model_path: Optional[str] = typer.Option(None, "--model-path"),
    verbose: bool = typer.Option(False, "--verbose"),
    report_json: Optional[Path] = typer.Option(None, "--report-json", dir_okay=False),
) -> None:
    """Analyze a file with a local LLM and write a censored copy plus an encrypted local map."""
    try:
        password = _resolve_password(password_prompt, password_env)
        engine = PersonaEngine(
            backend_config=_backend_config(backend, model_ref, base_url, cli_path, model_path)
        )
        result = engine.anonymize_document(
            input_path=input_file,
            password=password,
            out_dir=out_dir,
            review=review,
            report_json=report_json,
        )
    except PersonaError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=int(exc.exit_code)) from exc
    except Exception as exc:
        typer.echo(f"Error: unexpected internal failure: {exc}")
        raise typer.Exit(code=int(ExitCode.OPERATIONAL_ERROR)) from exc

    typer.echo(f"Censored file: {result.output_file}")
    typer.echo(f"Encrypted map: {result.map_file}")
    if verbose and result.warnings:
        for warning in result.warnings:
            typer.echo(f"Warning: {warning}")


@app.command()
def restore(
    censored_file: Path = typer.Argument(..., dir_okay=False),
    map_file: Path = typer.Option(..., "--map", dir_okay=False),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", file_okay=False),
    password_prompt: bool = typer.Option(False, "--password-prompt"),
    password_env: Optional[str] = typer.Option(None, "--password-env"),
    binding_mode: str = typer.Option(PRAGMATIC_BINDING_MODE, "--binding-mode"),
    verbose: bool = typer.Option(False, "--verbose"),
    report_json: Optional[Path] = typer.Option(None, "--report-json", dir_okay=False),
) -> None:
    """Restore a censored file from a validated encrypted map."""
    try:
        normalized_binding_mode = binding_mode.strip().lower()
        if normalized_binding_mode not in SUPPORTED_BINDING_MODES:
            raise InputValidationError(
                f"Unsupported binding mode '{binding_mode}'. Use '{PRAGMATIC_BINDING_MODE}' or '{STRICT_BINDING_MODE}'."
            )
        password = _resolve_password(password_prompt, password_env)
        engine = PersonaEngine()
        result = engine.restore_document(
            censored_path=censored_file,
            map_path=map_file,
            password=password,
            out_dir=out_dir,
            report_json=report_json,
            binding_mode=normalized_binding_mode,
        )
    except PersonaError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=int(exc.exit_code)) from exc
    except Exception as exc:
        typer.echo(f"Error: unexpected internal failure: {exc}")
        raise typer.Exit(code=int(ExitCode.OPERATIONAL_ERROR)) from exc

    typer.echo(f"Restored file: {result.output_file}")
    if result.has_integrity_issues:
        typer.echo(
            "Warning: restore completed with integrity issues "
            f"(binding={result.binding_status}, "
            f"{result.untouched_invalid_count} invalid placeholder(s), "
            f"{result.missing_expected_count} missing expected occurrence(s))."
        )
    if verbose and result.warnings:
        for warning in result.warnings:
            typer.echo(f"Warning: {warning}")
    if result.has_integrity_issues:
        raise typer.Exit(code=int(ExitCode.RESTORE_INTEGRITY_ERROR))


@app.command("app")
def run_app(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    backend: str = typer.Option("qwen-ollama", "--backend"),
    model_ref: Optional[str] = typer.Option(None, "--model-ref"),
    base_url: Optional[str] = typer.Option(None, "--base-url"),
    cli_path: Optional[str] = typer.Option(None, "--cli-path"),
    model_path: Optional[str] = typer.Option(None, "--model-path"),
) -> None:
    """Start the local Persona web app."""
    try:
        import uvicorn

        from persona.web.app import create_web_app

        engine = PersonaEngine(
            backend_config=_backend_config(backend, model_ref, base_url, cli_path, model_path)
        )
    except PersonaError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=int(exc.exit_code)) from exc
    uvicorn.run(create_web_app(engine=engine), host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
