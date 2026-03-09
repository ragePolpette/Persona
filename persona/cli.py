from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Optional

import typer

from persona.core.detection import parse_enabled_entities
from persona.core.pipeline import anonymize_file, restore_file
from persona.exceptions import ExitCode, PasswordResolutionError, PersonaError

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


@app.command()
def anonymize(
    input_file: Path = typer.Argument(..., dir_okay=False),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", file_okay=False),
    review: bool = typer.Option(True, "--review/--no-review"),
    password_prompt: bool = typer.Option(False, "--password-prompt"),
    password_env: Optional[str] = typer.Option(None, "--password-env"),
    entities: Optional[str] = typer.Option(None, "--entities"),
    verbose: bool = typer.Option(False, "--verbose"),
    report_json: Optional[Path] = typer.Option(None, "--report-json", dir_okay=False),
) -> None:
    """Analyze a file and write a censored copy plus an encrypted local map."""
    try:
        password = _resolve_password(password_prompt, password_env)
        result = anonymize_file(
            input_path=input_file,
            password=password,
            out_dir=out_dir,
            review=review,
            enabled_entities=parse_enabled_entities(entities),
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
    verbose: bool = typer.Option(False, "--verbose"),
    report_json: Optional[Path] = typer.Option(None, "--report-json", dir_okay=False),
) -> None:
    """Restore a censored file from a validated encrypted map."""
    try:
        password = _resolve_password(password_prompt, password_env)
        result = restore_file(
            censored_path=censored_file,
            map_path=map_file,
            password=password,
            out_dir=out_dir,
            report_json=report_json,
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
            f"({result.untouched_invalid_count} invalid placeholder(s), "
            f"{result.missing_expected_count} missing expected occurrence(s))."
        )
    if verbose and result.warnings:
        for warning in result.warnings:
            typer.echo(f"Warning: {warning}")
    if result.has_integrity_issues:
        raise typer.Exit(code=int(ExitCode.RESTORE_INTEGRITY_ERROR))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
