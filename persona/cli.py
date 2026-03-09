from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Optional

import typer

from persona.core.detection import parse_enabled_entities
from persona.core.pipeline import anonymize_file, restore_file
from persona.exceptions import PersonaError

app = typer.Typer(
    add_completion=False,
    help="Offline CLI for deterministic anonymization and strict restore of local documents.",
)


def _resolve_password(password_prompt: bool, password_env: Optional[str]) -> str:
    if password_env:
        value = os.environ.get(password_env)
        if value:
            return value
        raise typer.BadParameter(f"Environment variable '{password_env}' is not set.")
    if password_prompt or not password_env:
        return getpass.getpass("Persona password: ")
    raise typer.BadParameter("Provide --password-prompt or --password-env.")


@app.command()
def anonymize(
    input_file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
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
        raise typer.Exit(code=1) from exc

    typer.echo(f"Censored file: {result.output_file}")
    typer.echo(f"Encrypted map: {result.map_file}")
    if verbose and result.warnings:
        for warning in result.warnings:
            typer.echo(f"Warning: {warning}")


@app.command()
def restore(
    censored_file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    map_file: Path = typer.Option(..., "--map", exists=True, dir_okay=False, readable=True),
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
        raise typer.Exit(code=1) from exc

    typer.echo(f"Restored file: {result.output_file}")
    if verbose and result.warnings:
        for warning in result.warnings:
            typer.echo(f"Warning: {warning}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

