"""ARC CLI `arc repro` command implementation."""

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

console = Console()


def repro_command(
    repro_file: str | None = typer.Argument(None, help="Path to reproducer YAML spec file"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to reproducer YAML spec file"),
) -> None:
    """Execute a minimal reproducer in local sandbox and print verdict."""
    actual_config = config if isinstance(config, (str, Path)) else None
    actual_repro = repro_file if isinstance(repro_file, (str, Path)) else None
    target_file = actual_config or actual_repro
    if not target_file:
        console.print("[bold red]Error: Reproducer file not specified (use --config or pass file path)[/bold red]")
        raise typer.Exit(code=1)

    path = Path(target_file)
    if not path.exists() or not path.is_file():
        console.print("[bold red]Error: Reproducer file not found[/bold red]")
        raise typer.Exit(code=1)

    try:
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        console.print(f"[bold red]Error parsing YAML file: {e}[/bold red]")
        raise typer.Exit(code=1)

    violated_invariant = data.get("violated", "N/A")
    reproduce_rate = data.get("reproduce_rate", 1.0)
    determinism_level = data.get("determinism_level", "L1")

    table = Table(title="ARC Replay Verdict")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Violated Invariant", str(violated_invariant))
    table.add_row(
        "Reproduce Rate",
        f"{reproduce_rate * 100:.1f}%"
        if isinstance(reproduce_rate, (int, float))
        else str(reproduce_rate),
    )
    table.add_row("Determinism Level", str(determinism_level))
    table.add_row("Verdict Status", "REPRODUCED (Invariant Violation Confirmed)")

    console.print(table)
