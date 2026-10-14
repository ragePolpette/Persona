from __future__ import annotations

import functools
import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import typer

from persona.documents import SUPPORTED_SUFFIXES, Document, TextDocument, decode_text, open_document
from persona.engine import Leak, analyze, apply, verify
from persona.exceptions import InputError, PersonaError
from persona.placeholders import KINDS
from persona.restore import placeholders_in, restore_segments
from persona.review import run_review
from persona.vault import Vault

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Anonymize a document, share it with an AI, restore what comes back.",
)
glossary_app = typer.Typer(no_args_is_help=True, help="Names to always mask in a project.")
app.add_typer(glossary_app, name="glossary")
allow_app = typer.Typer(no_args_is_help=True, help="Values that must never be masked (false positives).")
app.add_typer(allow_app, name="allow")

ProjectOption = typer.Option(None, "--project", "-p", help="Project name (vault in ~/.persona/projects).")
VaultOption = typer.Option(None, "--vault", help="Explicit vault path (overrides --project).")


def _home() -> Path:
    return Path(os.environ.get("PERSONA_HOME", Path.home() / ".persona"))


def _vault_path(project: str | None, vault: Path | None) -> Path:
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


def _open(project: str | None, vault: Path | None) -> Vault:
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
def init(project: str | None = ProjectOption, vault: Path | None = VaultOption) -> None:
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
    project: str | None = ProjectOption,
    vault: Path | None = VaultOption,
) -> None:
    """Add a name (and aliases) to the project glossary."""
    opened = _open(project, vault)
    item = opened.add_glossary(term, kind.upper(), alias)
    opened.save()
    typer.echo(f"{item.kind}: {', '.join(item.all_forms)}")


@glossary_app.command("list")
@_guard
def glossary_list(project: str | None = ProjectOption, vault: Path | None = VaultOption) -> None:
    """Show the project glossary."""
    for item in _open(project, vault).glossary:
        typer.echo(f"{item.kind:10} {', '.join(item.all_forms)}")


@glossary_app.command("remove")
@_guard
def glossary_remove(
    term: str = typer.Argument(...),
    project: str | None = ProjectOption,
    vault: Path | None = VaultOption,
) -> None:
    """Remove a name from the project glossary."""
    opened = _open(project, vault)
    if not opened.remove_glossary(term):
        raise InputError(f"'{term}' is not in the glossary.")
    opened.save()
    typer.echo(f"Removed: {term}")


@allow_app.command("add")
@_guard
def allow_add(
    value: str = typer.Argument(..., help="Text that must never be masked, e.g. 'Aurora Borealis'"),
    project: str | None = ProjectOption,
    vault: Path | None = VaultOption,
) -> None:
    """Never mask this value (case/accent-insensitive)."""
    opened = _open(project, vault)
    opened.allow(value)
    opened.save()
    typer.echo(f"Allowed: {value}")


@allow_app.command("list")
@_guard
def allow_list(project: str | None = ProjectOption, vault: Path | None = VaultOption) -> None:
    """Show the values that are never masked."""
    for value in _open(project, vault).allowlist:
        typer.echo(value)


@allow_app.command("remove")
@_guard
def allow_remove(
    value: str = typer.Argument(...),
    project: str | None = ProjectOption,
    vault: Path | None = VaultOption,
) -> None:
    """Mask this value again."""
    opened = _open(project, vault)
    if not opened.disallow(value):
        raise InputError(f"'{value}' is not in the allowlist.")
    opened.save()
    typer.echo(f"No longer allowed: {value}")


@app.command()
@_guard
def rekey(project: str | None = ProjectOption, vault: Path | None = VaultOption) -> None:
    """Re-encrypt the vault with a new password (fresh salt, current KDF settings)."""
    opened = _open(project, vault)
    new_password = os.environ.get("PERSONA_NEW_PASSWORD") or typer.prompt(
        "New vault password", hide_input=True, confirmation_prompt=True
    )
    if not new_password:
        raise InputError("The new password cannot be empty.")
    removed = opened.rekey(new_password)
    typer.echo(f"Vault re-encrypted: {opened.path}")
    if removed:
        typer.echo(f"Removed {len(removed)} backup(s) encrypted with the old password.")


@dataclass(slots=True)
class FileReport:
    source: str
    status: str  # written | blocked | dry-run | skipped | error
    output: str | None = None
    masked: int = 0
    distinct: int = 0
    leaks: int = 0
    detections: dict[str, int] = field(default_factory=dict)
    warnings: int = 0
    error: str | None = None

    def as_json(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


_STATUS_ORDER = ("written", "dry-run", "blocked", "skipped", "error")
_STATUS_EXIT = {"blocked": 2, "error": 1}


@app.command()
@_guard
def anonymize(
    path: Path | None = typer.Argument(None, exists=True, help="File, or directory of files, to anonymize."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Default: <name>.anon.<ext> (.txt for PDFs). A directory for a directory input."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be masked."),
    force: bool = typer.Option(False, "--force", help="Write the file even if the safety check finds leaks."),
    review: bool = typer.Option(False, "--review", help="Go through each detection before masking."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Do not mask this exact text (this time only)."),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="With a directory: include subdirectories."),
    stdin: bool = typer.Option(False, "--stdin", help="Read text from standard input (written to standard output)."),
    stdout: bool = typer.Option(False, "--stdout", help="Write the anonymized text to standard output."),
    json_report: bool = typer.Option(
        False, "--json", help="Print a JSON report on standard output (counts only, never the masked values)."
    ),
    project: str | None = ProjectOption,
    vault: Path | None = VaultOption,
) -> None:
    """Mask sensitive data. The written file is re-read and checked before it is declared shareable."""
    if stdin == (path is not None):
        raise InputError("Give either a FILE/DIRECTORY or --stdin.")
    is_dir = path is not None and path.is_dir()
    if review and (stdin or json_report):
        raise InputError("--review is interactive: it cannot be combined with --stdin or --json.")
    if json_report and (stdout or (stdin and out is None)):
        raise InputError("--json uses standard output: write the text with --out instead.")
    if is_dir and stdout:
        raise InputError("--stdout works with a single text input, not a directory.")
    if recursive and not is_dir:
        raise InputError("--recursive needs a directory.")
    if review and dry_run:
        typer.secho("Warning: --review is ignored with --dry-run.", fg=typer.colors.YELLOW, err=True)
        review = False
    to_stdout = stdout or (stdin and out is None)
    say = (lambda message, err=False: None) if json_report else _say(to_stdout)
    excluded = {value.strip() for value in exclude}

    if stdin:
        text, _ = decode_text(typer.get_binary_stream("stdin").read())
        jobs: list[tuple[Path, Path | None]] = [(Path("<stdin>"), out)]
        loaded: dict[Path, Document] = {jobs[0][0]: TextDocument(jobs[0][0], text, output_suffix=".txt")}
    elif is_dir:
        jobs, loaded = _directory_jobs(path, out, recursive=recursive), {}
    else:
        jobs, loaded = [(path, out)], {}
    opened = _open(project, vault)

    reports: list[FileReport] = []
    for source, target in jobs:
        if is_dir and source.suffix.lower() not in SUPPORTED_SUFFIXES:
            reports.append(FileReport(str(source), "skipped", error=f"unsupported file type '{source.suffix}'"))
            continue
        try:
            document = loaded.get(source) or open_document(source)
        except InputError as exc:
            if not is_dir:
                raise
            reports.append(FileReport(str(source), "error", error=str(exc)))
            say(f"Error in {source}: {exc}", err=True)
            continue
        if to_stdout and not isinstance(document, TextDocument):
            raise InputError("--stdout works only with text input (.txt, .md, .pdf).")
        if is_dir:
            say(f"== {source}")
        try:
            report = _anonymize_document(
                source,
                document,
                target,
                opened,
                dry_run=dry_run,
                force=force,
                review=review,
                excluded=excluded,
                to_stdout=to_stdout,
                into_directory=is_dir,
                say=say,
            )
            reports.append(report)
        except PersonaError as exc:
            if not is_dir:
                raise
            reports.append(FileReport(str(source), "error", error=str(exc)))
            say(f"Error in {source}: {exc}", err=True)

    if json_report:
        summary = {status: sum(r.status == status for r in reports) for status in _STATUS_ORDER}
        typer.echo(json.dumps({"files": [r.as_json() for r in reports], "summary": summary}, indent=2))
    elif is_dir:
        counts = ", ".join(f"{n} {status}" for status in _STATUS_ORDER if (n := sum(r.status == status for r in reports)))
        say(f"{len(reports)} file(s): {counts or 'nothing to do'}.", err=to_stdout)
    codes = {_STATUS_EXIT.get(report.status, 0) for report in reports}
    if 2 in codes or 1 in codes:
        raise typer.Exit(code=2 if 2 in codes else 1)


def _say(to_stdout: bool):
    def say(message: str, err: bool = False) -> None:
        typer.echo(message, err=err or to_stdout)

    return say


def _directory_jobs(root: Path, out: Path | None, *, recursive: bool) -> list[tuple[Path, Path | None]]:
    """Files under `root`, skipping hidden files and earlier outputs (*.anon.*, *.restored.*)."""
    candidates = root.rglob("*") if recursive else root.glob("*")
    jobs: list[tuple[Path, Path | None]] = []
    resolved_out = out.resolve() if out is not None else None
    for file in sorted(candidates):
        relative = file.relative_to(root)
        if not file.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        if file.stem.endswith((".anon", ".restored")):
            continue
        if resolved_out is not None and resolved_out in file.resolve().parents:
            continue
        jobs.append((file, None if out is None else out / relative.parent))
    return jobs


def _anonymize_document(
    source: Path,
    document: Document,
    target: Path | None,
    opened: Vault,
    *,
    dry_run: bool,
    force: bool,
    review: bool,
    excluded: set[str],
    to_stdout: bool,
    into_directory: bool,
    say,
) -> FileReport:
    if review:
        analysis = run_review(
            lambda: analyze(document.segments, opened),
            opened,
            lambda prompt, default: typer.prompt(prompt, default=default, show_default=False),
            typer.echo,
        )
        opened.save()  # glossary and allowlist decisions are worth keeping even if the run fails later
    else:
        analysis = analyze(document.segments, opened)
    for span in analysis.spans:
        if span.text in excluded:
            span.approved = False
    accepted = {span.text for span in analysis.spans if not span.approved}  # the user chose to leave these in
    report = FileReport(str(source), "dry-run", warnings=len(document.warnings))

    if dry_run:
        grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
        for span in analysis.spans:
            if span.approved:
                grouped[(span.kind, span.text)].append(span.source)
        for (kind, value), sources in sorted(grouped.items()):
            say(f"{kind:10} x{len(sources)}  {value!r}  ({sources[0]})")
            report.detections[kind] = report.detections.get(kind, 0) + len(sources)
        say(f"{len(analysis.spans)} occurrence(s), {len(grouped)} distinct value(s). Nothing written.")
        _print_warnings(document, say)
        return report

    result = apply(analysis, opened)
    report.masked, report.distinct = sum(result.placeholders.values()), len(result.placeholders)
    if to_stdout:
        assert isinstance(document, TextDocument)
        rendered = document.render(result.edits)
        leaks = verify({"text": rendered}, opened, accepted=accepted)
        if not _passes_safety_check(leaks, force, say, report):
            return report
        opened.save()  # the mapping must be on disk before the anonymized text leaves this process
        typer.echo(rendered, nl=False)
        report.status = "written"
        say(f"Written to standard output  ({report.masked} masked, {report.distinct} distinct)", err=True)
    else:
        if target is None or into_directory:
            folder = target if target is not None else source.parent
            target = folder / f"{source.stem}.anon{document.output_suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.stem}.staging{target.suffix}")
        try:
            document.write(staging, result.edits)
            written = open_document(staging)  # check what was actually written, not what we meant to write
            leaks = verify({segment.id: segment.text for segment in written.segments}, opened, accepted=accepted)
            if not _passes_safety_check(leaks, force, say, report):
                return report
            opened.save()  # the mapping must be on disk before the anonymized file appears
            os.replace(staging, target)
        finally:
            staging.unlink(missing_ok=True)
        report.status, report.output = "written", str(target)
        say(f"Written: {target}  ({report.masked} masked, {report.distinct} distinct)")
    _print_warnings(document, say)
    if leaks:
        say(f"Warning: {len(leaks)} leak(s) ignored because of --force.", err=True)
    return report


def _passes_safety_check(leaks: list[Leak], force: bool, say, report: FileReport) -> bool:
    report.leaks = len(leaks)
    if not leaks or force:
        return True
    report.status = "blocked"
    say("Safety check FAILED: sensitive data still present. Nothing written.", err=True)
    for leak in leaks:
        say(f"  {leak.text!r}  ({leak.reason})", err=True)
    say("Add the names to the glossary (persona glossary add) and retry, or use --force.", err=True)
    return False


@app.command("verify")
@_guard
def verify_cmd(
    file: Path = typer.Argument(..., exists=True, dir_okay=False),
    project: str | None = ProjectOption,
    vault: Path | None = VaultOption,
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
    sent: Path | None = typer.Option(None, "--sent", help="The anonymized file you sent, to detect dropped placeholders."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Default: <name>.restored<ext>"),
    project: str | None = ProjectOption,
    vault: Path | None = VaultOption,
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


def _print_warnings(document, say=None) -> None:
    for warning in document.warnings:
        if say is None:
            typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW, err=True)
        else:
            say(f"Warning: {warning}", err=True)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
