"""ARC CLI `arc minimize` command implementation using Delta-Debugging (`ddmin`).

Minimizes long, noisy fault chains in reproducer YAML artifacts to the smallest
reproducible fault sequence required to trigger invariant violations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arc.cli.commands.repro import extract_invariant_spec, find_trace_file
from arc.execution.fork_engine.delta_debugging import IrreproducibleBugError, ddmin
from arc.execution.fork_engine.fault_catalog import FaultCatalog
from arc.execution.fork_engine.reproducer_export import export_minimal_reproducer_yaml
from arc.execution.sandbox_runner.runner import SandboxRunner

console = Console()


def minimize_command(
    repro_file: str = typer.Argument(..., help="Path to reproducer YAML spec file to minimize"),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Target path for minimized reproducer YAML (default: arc-repro-<stem>-min.yaml)",
    ),
    trace: str | None = typer.Option(None, "--trace", "-t", help="Override trace identifier"),
) -> None:
    """Run Delta-Debugging (`ddmin`) to minimize fault sequences in bug reproducer YAML artifacts."""
    path = Path(repro_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        console.print(f"[bold red]Error: Reproducer file not found ({path})[/bold red]")
        raise typer.Exit(code=1)

    try:
        with open(path, encoding="utf-8") as f_in:
            data: dict[str, Any] = yaml.safe_load(f_in) or {}
    except (yaml.YAMLError, OSError) as e:
        console.print(f"[bold red]Error parsing YAML file '{path}': {e}[/bold red]")
        raise typer.Exit(code=1)

    raw_faults = data.get("faults") or data.get("fault") or data.get("fault_chain") or []
    faults_list: list[dict[str, Any]] = []
    if isinstance(raw_faults, dict):
        faults_list = [raw_faults]
    elif isinstance(raw_faults, list):
        for item in raw_faults:
            if isinstance(item, dict):
                faults_list.append(item)
            elif isinstance(item, str):
                faults_list.append({"type": item, "step": 0, "tool": "N/A"})

    trace_id = trace or str(data.get("trace") or data.get("trace_id") or "N/A")
    violated = str(data.get("violated") or data.get("violated_invariant") or "INV-UNKNOWN")
    det_level = str(data.get("determinism_level", "L1"))
    cwd = Path.cwd()

    console.print(f"[bold cyan]🔍 Starting Delta-Debugging (`ddmin`) for:[/bold cyan] {path.name}")
    console.print(f"  Initial fault count: [bold yellow]{len(faults_list)}[/bold yellow] faults")
    console.print(f"  Target Invariant:    [bold red]{violated}[/bold red]\n")

    if len(faults_list) <= 1:
        console.print("[dim yellow]Fault sequence has 1 or fewer faults. Already minimal.[/dim yellow]")
        minimized = faults_list
    else:
        # Build CassettePlayer from trace if available
        trace_file = find_trace_file(trace_id, cwd)
        cassette_player = None
        if trace_file is not None:
            try:
                from arc.execution.sandbox_runner.cassette_player import CassettePlayer
                trace_json = json.loads(trace_file.read_text(encoding="utf-8"))
                steps = trace_json.get("steps", [])
                cassette_records = [
                    {
                        "tool": s["request"]["tool"],
                        "request_args": s["request"].get("args", {}),
                        "response": s.get("response", {"status": "ok"}),
                    }
                    for s in steps
                    if isinstance(s.get("request"), dict) and "tool" in s["request"]
                ]
                if cassette_records:
                    cassette_player = CassettePlayer(records=cassette_records)
            except Exception:  # noqa: BLE001
                pass

        inv_spec = extract_invariant_spec(violated, cwd)
        if not inv_spec and "check" in data:
            inv_spec = {
                "id": violated,
                "statement": str(data.get("statement") or violated),
                "category": str(data.get("category") or "safety"),
                "check": str(data.get("check") or "True"),
                "severity": str(data.get("severity") or "critical"),
            }

        target_inv_spec: dict[str, Any] = inv_spec or {
            "id": violated,
            "statement": violated,
            "category": "safety",
            "check": "len(effects) <= 1" if any(w in violated.lower() for w in ["idem", "dup", "pay", "refund"]) else "len(effects) == 0",
            "severity": "critical",
        }

        def test_subset(subset: list[dict[str, Any]]) -> bool:
            runner = SandboxRunner()
            catalog = FaultCatalog.from_list(subset)
            res = runner.run_with_faults(
                fault_spec=catalog,
                target_invariant=target_inv_spec,
                cassette_player=cassette_player,
            )
            return not res.get("passed", True)

        try:
            minimized = ddmin(faults_list, test_subset)
            console.print(f"[bold green]✓ Reduction complete:[/bold green] {len(faults_list)} → {len(minimized)} faults")
        except IrreproducibleBugError:
            console.print(
                "[dim yellow]Warning: Full fault sequence did not trigger violation in local sandbox. "
                "Returning unminimized fault sequence.[/dim yellow]"
            )
            minimized = faults_list

    # Determine destination output path
    dest_path = (
        Path(output)
        if output
        else path.parent / f"{path.stem}-min.yaml"
    )

    out_file = export_minimal_reproducer_yaml(
        trace=trace_id,
        faults=minimized,
        violated=violated,
        determinism_level=det_level,
        reproduce_rate=data.get("reproduce_rate", 1.0),
        confidence_interval=data.get("confidence_interval"),
        cost_usd=data.get("cost_usd", 0.0),
        output_path=dest_path,
    )

    table = Table(title="[bold green]Delta-Debugging Reduction Summary[/bold green]")
    table.add_column("Property", style="cyan")
    table.add_column("Before", style="yellow")
    table.add_column("After (`ddmin`)", style="bold green")

    table.add_row("Fault Count", str(len(faults_list)), str(len(minimized)))
    table.add_row("Reduction Ratio", "100%", f"{round(len(minimized) / max(len(faults_list), 1) * 100, 1)}%")
    table.add_row("Output File", path.name, out_file.name)

    console.print()
    console.print(table)
    console.print(
        Panel(
            f"[bold green]Minimized bug reproducer written to:[/bold green] [cyan]{out_file}[/cyan]\n"
            f"Run replay with: [yellow]arc repro {out_file}[/yellow]",
            title="[bold blue]Export Result[/bold blue]",
            border_style="green",
        )
    )
