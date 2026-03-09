from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    add_completion=False,
    help="Offline CLI for deterministic anonymization and strict restore of local documents.",
)


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
    raise typer.Exit("Command baseline created; implementation follows in next phases.")


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
    raise typer.Exit("Command baseline created; implementation follows in next phases.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

