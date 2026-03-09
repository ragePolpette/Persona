from __future__ import annotations

from collections.abc import Callable, Iterable

from rich.console import Console

from persona.core.placeholders import build_placeholder, validate_masked_payload
from persona.exceptions import PlaceholderValidationError, ReviewAbortedError
from persona.models.entities import DetectionMatch

PromptFunc = Callable[[str], str]


def review_matches(
    matches: Iterable[DetectionMatch],
    prompt: PromptFunc = input,
    console: Console | None = None,
) -> list[DetectionMatch]:
    reviewed: list[DetectionMatch] = []
    active_console = console or Console()
    for match in matches:
        active_console.print(f"\n[bold]Match {match.match_id}[/bold]")
        active_console.print(f"Type: {match.entity_type}")
        active_console.print(f"Value: {match.original_value}")
        active_console.print(f"Context: {match.context}")
        active_console.print(f"Location: {match.location}")
        active_console.print(f"Proposed: {match.placeholder}")

        while True:
            action = prompt("Action [a]pprove/[r]eject/[e]dit/[q]uit (default a): ").strip().lower() or "a"
            if action in {"a", "approve"}:
                match.approved = True
                reviewed.append(match)
                break
            if action in {"r", "reject"}:
                match.approved = False
                reviewed.append(match)
                break
            if action in {"e", "edit"}:
                candidate = prompt("New masked payload: ")
                try:
                    validate_masked_payload(candidate)
                except PlaceholderValidationError as exc:
                    active_console.print(f"[red]{exc}[/red]")
                    continue
                match.masked_value = candidate
                match.placeholder = build_placeholder(match.token_id, candidate)
                match.approved = True
                reviewed.append(match)
                break
            if action in {"q", "quit"}:
                raise ReviewAbortedError("Review aborted by user.")
            active_console.print("[yellow]Unknown action. Use a, r, e, or q.[/yellow]")
    return reviewed

