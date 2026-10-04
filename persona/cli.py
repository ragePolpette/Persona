from __future__ import annotations

import functools
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

import typer

from persona.documents import open_document
from persona.engine import analyze, apply, verify
from persona.exceptions import InputError, PersonaError
from persona.placeholders import KINDS
from persona.restore import placeholders_in, restore_segments
from persona.vault import Vault

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Anonymize a document, share it with an AI, restore what comes back.",
)
glossary_app = typer.Typer(no_args_is_help=True, help="Names to always mask in a project.")
app.add_typer(glossary_app, name="glossary")

ProjectOption = typer.Option(None, "--project", "-p", help="Project name (vault in ~/.persona/projects).")
VaultOption = typer.Option(None, "--vault", help="Explicit vault path (overrides --project).")


def _home() -> Path:
    return Path(os.environ.get("PERSONA_HOME", Path.home() / ".persona"))


def _vault_path(project: Optional[str], vault: Optional[Path]) -> Path:
    if vault is not None:
        return vault
    if not project:
        raise InputError("Specify --project NAME (or --vault PATH).")
    return _home() / "projects" / f"{project}.vault"


def _password(confirm: bool = False) -> str:
    value = os.environ.get("PERSONA_PASSWORD")
    if value:
        return value
    return typer.prompt("Vault password", hide_input=True, confirmation_prompt=confirm)


def _open(project: Optional[str], vault: Optional[Path]) -> Vault:
    return Vault.open(_vault_path(project, vault), _password())


def _guard(action):
    @functools.wraps(action)
    def wrapper(*args, **kwargs):
        try:
            return action(*args, **kwargs)
        except PersonaError as exc:
            typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc

    return wrapper


@app.command()
@_guard
def init(project: Optional[str] = ProjectOption, vault: Optional[Path] = VaultOption) -> None:
    """Create an encrypted vault for a project."""
    path = _vault_path(project, vault)
    Vault.create(path, _password(confirm=True))
    typer.echo(f"Vault created: {path}")


@glossary_app.command("add")
@_guard
def glossary_add(
    term: str = typer.Argument(..., help="Name to always mask, e.g. 'Tessitura Valdarno S.r.l.'"),
    kind: str = typer.Option("ALTRO", "--kind", "-k", help=f"One of: {', '.join(KINDS)}"),
    alias: list[str] = typer.Option([], "--alias", "-a", help="Other ways the name is written."),
    project: Optional[str] = ProjectOption,
    vault: Optional[Path] = VaultOption,
) -> None:
    """Add a name (and aliases) to the project glossary."""
    opened = _open(project, vault)
    item = opened.add_glossary(term, kind.upper(), alias)
    opened.save()
    typer.echo(f"{item.kind}: {', '.join(item.all_forms)}")


@glossary_app.command("list")
@_guard
def glossary_list(project: Optional[str] = ProjectOption, vault: Optional[Path] = VaultOption) -> None:
    """Show the project glossary."""
    for item in _open(project, vault).glossary:
        typer.echo(f"{item.kind:10} {', '.join(item.all_forms)}")


@app.command()
@_guard
def anonymize(
    file: Path = typer.Argument(..., exists=True, dir_okay=False),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Default: <name>.anon.<ext> (.txt for PDFs)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be masked."),
    force: bool = typer.Option(False, "--force", help="Write the file even if the safety check finds leaks."),
    project: Optional[str] = ProjectOption,
    vault: Optional[Path] = VaultOption,
) -> None:
    """Mask sensitive data. The written file is re-read and checked before it is declared shareable."""
    document = open_document(file)
    opened = _open(project, vault)
    analysis = analyze(document.segments, opened)

    if dry_run:
        grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
        for span in analysis.spans:
            grouped[(span.kind, span.text)].append(span.source)
        for (kind, value), sources in sorted(grouped.items()):
            typer.echo(f"{kind:10} x{len(sources)}  {value!r}  ({sources[0]})")
        typer.echo(f"{len(analysis.spans)} occurrence(s), {len(grouped)} distinct value(s). Nothing written.")
        _print_warnings(document)
        return

    result = apply(analysis, opened)
    target = out or file.with_name(f"{file.stem}.anon{document.output_suffix}")
    staging = target.with_name(f".{target.stem}.staging{target.suffix}")
    try:
        document.write(staging, result.edits)
        written = open_document(staging)  # check what was actually written, not what we meant to write
        leaks = verify({segment.id: segment.text for segment in written.segments}, opened)
        if leaks and not force:
            typer.secho("Safety check FAILED: sensitive data still present. Nothing written.", fg=typer.colors.RED, err=True)
            for leak in leaks:
                typer.echo(f"  {leak.text!r}  ({leak.reason})", err=True)
            typer.echo("Add the names to the glossary (persona glossary add) and retry, or use --force.", err=True)
            raise typer.Exit(code=2)
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    opened.save()
    typer.echo(f"Written: {target}  ({sum(result.placeholders.values())} masked, {len(result.placeholders)} distinct)")
    _print_warnings(document)
    if leaks:
        typer.secho(f"Warning: {len(leaks)} leak(s) ignored because of --force.", fg=typer.colors.YELLOW, err=True)


@app.command("verify")
@_guard
def verify_cmd(
    file: Path = typer.Argument(..., exists=True, dir_okay=False),
    project: Optional[str] = ProjectOption,
    vault: Optional[Path] = VaultOption,
) -> None:
    """Check a file for sensitive data before sharing it."""
    document = open_document(file)
    leaks = verify({segment.id: segment.text for segment in document.segments}, _open(project, vault))
    for leak in leaks:
        typer.echo(f"{leak.text!r}  ({leak.reason})")
    _print_warnings(document)
    if leaks:
        raise typer.Exit(code=2)
    typer.echo("OK: nothing sensitive found.")


@app.command()
@_guard
def restore(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="The AI's output."),
    sent: Optional[Path] = typer.Option(None, "--sent", help="The anonymized file you sent, to detect dropped placeholders."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Default: <name>.restored<ext>"),
    project: Optional[str] = ProjectOption,
    vault: Optional[Path] = VaultOption,
) -> None:
    """Put the original values back into the AI's output."""
    opened = _open(project, vault)
    document = open_document(file)
    expected: set[str] | None = None
    if sent:
        expected = set()
        for segment in open_document(sent).segments:
            expected |= placeholders_in(segment.text)
    edits, report = restore_segments(document.segments, opened, expected=expected)
    target = out or file.with_name(f"{file.stem}.restored{document.output_suffix}")
    document.write(target, edits)
    typer.echo(f"Written: {target}  ({sum(report.restored.values())} placeholder(s) restored)")
    for raw, canonical in report.altered:
        typer.secho(f"Note: '{raw}' was altered, read as {canonical}", fg=typer.colors.YELLOW)
    for raw in report.invented:
        typer.secho(f"Warning: '{raw}' is not in the vault (invented by the AI?). Left as is.", fg=typer.colors.YELLOW)
    for placeholder in report.missing:
        typer.secho(f"Warning: {placeholder} was sent but is missing from the output.", fg=typer.colors.YELLOW)
    if not report.clean:
        raise typer.Exit(code=3)


def _print_warnings(document) -> None:
    for warning in document.warnings:
        typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW, err=True)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
