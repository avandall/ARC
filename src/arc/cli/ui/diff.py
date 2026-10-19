"""Interactive Diff Box for code mutation review (TASK-CLI-004).

Renders side-by-side / inline unified diffs with green (+) and red (-) lines
and provides an interactive prompt for approving or rejecting AST changes.
"""

from __future__ import annotations

import questionary
from rich.console import Console
from rich.panel import Panel

from arc.cli.tracer.scanner import TraceCandidate, apply_candidate

console = Console()


def render_diff_box(candidate: TraceCandidate, box_title: str | None = None) -> Panel:
    """Renders candidate diff inside a styled Rich panel."""
    diff_lines: list[str] = []
    for line in candidate.diff_snippet.splitlines():
        if line.startswith("-"):
            diff_lines.append(f"[bold red]{line}[/bold red]")
        elif line.startswith("+"):
            diff_lines.append(f"[bold green]{line}[/bold green]")
        else:
            diff_lines.append(f"[dim]{line}[/dim]")

    formatted_diff = "\n".join(diff_lines)
    header = (
        f"[bold]Target File:[/bold] {candidate.file_path} (Line {candidate.line_number})\n"
        f"[bold]Function:[/bold] def [cyan]{candidate.function_name}[/cyan]\n"
        f"[bold]Suggested Decorator:[/bold] [yellow]@{candidate.decorator_type}[/yellow]\n\n"
        f"{formatted_diff}"
    )

    title = box_title or f"Auto Tracer Diff: {candidate.function_name}"
    return Panel(
        header,
        title=f"[bold cyan]{title}[/bold cyan]",
        border_style="cyan",
        expand=False,
    )


def review_and_apply_candidates(
    candidates: list[TraceCandidate],
    interactive: bool = True,
) -> list[TraceCandidate]:
    """Iterates through tracing candidates with an interactive diff review box.

    Prompts:
        [y] Accept & Apply: Apply modification to source file
        [n] Reject: Skip candidate
        [a] Accept All: Apply current and all remaining candidates
        [q] Cancel: Exit review immediately

    Returns:
        List of accepted and applied TraceCandidate instances.
    """
    applied: list[TraceCandidate] = []
    accept_all = not interactive

    for idx, cand in enumerate(candidates, start=1):
        if not accept_all:
            console.print(
                render_diff_box(
                    cand,
                    box_title=f"Candidate [{idx}/{len(candidates)}]: {cand.function_name}",
                )
            )

            choice = questionary.select(
                f"Apply @{cand.decorator_type} to '{cand.function_name}'?",
                choices=[
                    "[y] Accept & Apply",
                    "[n] Reject",
                    "[a] Accept All",
                    "[q] Cancel",
                ],
            ).ask()

            if choice is None or choice.startswith("[q]"):
                console.print("[dim]Review cancelled by user.[/dim]")
                break
            if choice.startswith("[a]"):
                accept_all = True
            elif choice.startswith("[n]"):
                console.print(f"[dim]Skipped {cand.function_name}.[/dim]")
                continue

        # Apply candidate
        apply_candidate(cand)
        applied.append(cand)
        console.print(
            f"[green]✓ Applied @{cand.decorator_type} to {cand.function_name} in {cand.file_path}[/green]"
        )

    return applied
