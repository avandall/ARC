"""ARC CLI `arc incidents` command implementation (TASK-P4-003).

Provides incident tagging interface (`arc incidents tag --trace <id> --escaped-bug --linked-invariant <inv_id>`).
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from arc.control_plane.warehouse.db_store import DatabaseStore
from arc.control_plane.warehouse.escaped_bugs import EscapedBugTracker

incidents_app = typer.Typer(
    name="incidents",
    help="Escaped Bug Tracker & Incident Tagging Management",
    add_completion=False,
)

console = Console()


@incidents_app.command("tag")
def tag_command(
    trace_id: str = typer.Option(
        ...,
        "--trace",
        "-t",
        help="Target CTF trace ID",
    ),
    escaped_bug: bool = typer.Option(
        True,
        "--escaped-bug/--no-escaped-bug",
        help="Flag indicating whether this incident is an escaped bug caused by agent",
    ),
    linked_invariant: str | None = typer.Option(
        None,
        "--linked-invariant",
        "-i",
        help="Linked catalog invariant ID (e.g. INV-PAY-002)",
    ),
    root_cause: str = typer.Option(
        "",
        "--root-cause",
        "-r",
        help="Detailed root cause description of the incident",
    ),
    tagged_by: str = typer.Option(
        "engineer",
        "--tagged-by",
        help="User or engineer tagging the incident",
    ),
) -> None:
    """Tags an incident as an escaped bug and updates invariant false_negative or miner suggestions."""
    db_store = DatabaseStore.get_shared_instance()
    tracker = EscapedBugTracker(db_store=db_store)
    try:
        bug = tracker.tag_incident(
            trace_id=trace_id,
            escaped_bug=escaped_bug,
            linked_invariant=linked_invariant,
            root_cause=root_cause,
            tagged_by=tagged_by,
        )
    except ValueError as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(code=1) from e

    inv_str = f"Linked Invariant: [cyan]{linked_invariant}[/cyan]" if linked_invariant else "No linked invariant (Auto-created miner suggestion)"
    console.print(
        Panel(
            f"[bold green]Incident tagged successfully![/bold green]\n"
            f"Incident ID: [cyan]{bug['incident_id']}[/cyan]\n"
            f"Trace ID: [yellow]{bug['trace_id']}[/yellow]\n"
            f"Escaped Bug: [magenta]{bug['is_agent_caused']}[/magenta]\n"
            f"{inv_str}\n"
            f"Root Cause: {root_cause}",
            title="[bold blue]ARC Incident Tagging[/bold blue]",
        )
    )
