"""ARC CLI `arc gate` command implementation."""

from __future__ import annotations

import os
import sys

import typer
from rich.console import Console
from rich.table import Table

# Ensure execution/fork-engine directory is in sys.path
fork_engine_dir = os.path.abspath("execution/fork-engine")
if fork_engine_dir not in sys.path:
    sys.path.insert(0, fork_engine_dir)

try:
    from gate_evaluator import CIGateExitCode, GateEvaluator
except ImportError:
    from execution.fork_engine.gate_evaluator import (  # type: ignore[no-redef]
        CIGateExitCode,
        GateEvaluator,
    )

console = Console()


def gate_command(
    profile: str = typer.Option(
        "smoke",
        "--profile",
        "-p",
        help="CI Gate profile: 'smoke' (K=3, critical only) or 'full' (K=20, entire catalog)",
    ),
    budget_usd: float | None = typer.Option(
        None,
        "--budget-usd",
        "-b",
        help="Maximum budget ceiling in USD",
    ),
    trace: str | None = typer.Option(
        None,
        "--trace",
        "-t",
        help="Trace ID to evaluate in CI gate",
    ),
    baseline_ci_lower: float = typer.Option(
        0.0,
        "--baseline-ci-lower",
        help="Baseline Wilson CI lower bound",
    ),
    baseline_ci_upper: float = typer.Option(
        0.0,
        "--baseline-ci-upper",
        help="Baseline Wilson CI upper bound",
    ),
) -> None:
    """Run ARC CI Gate evaluation on trace and exit with standard POSIX code (0/1/2/3)."""
    evaluator = GateEvaluator(
        profile=profile,
        budget_usd=budget_usd,
        baseline_ci=(baseline_ci_lower, baseline_ci_upper),
    )

    result = evaluator.evaluate(trace_id=trace)

    table = Table(title=f"ARC CI Gate Summary [Profile: {profile.upper()}]")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Status", result.status)
    table.add_row("Exit Code", str(int(result.exit_code)))
    table.add_row("Profile", result.profile)
    table.add_row("K Branches", str(result.k))
    table.add_row("Reason", result.reason)
    table.add_row("Total Cost (USD)", f"${result.total_cost_usd:.4f}")

    console.print(table)

    if result.exit_code == CIGateExitCode.SUCCESS:
        console.print(
            f"[bold green]PASS: CI Gate evaluation successful (Exit code {int(result.exit_code)})[/bold green]"
        )
    elif result.exit_code == CIGateExitCode.CRITICAL_VIOLATION:
        console.print(
            f"[bold red]FAIL: Critical invariant violation confirmed (Exit code {int(result.exit_code)})[/bold red]"
        )
        if result.violations:
            console.print("[bold red]Violations Summary:[/bold red]")
            for inv_id, vdata in result.violations.items():
                ci = vdata.get("wilson_ci", [0.0, 0.0])
                console.print(f"  - {inv_id}: Rate={vdata.get('violation_rate')}, 95% CI={ci}")
    elif result.exit_code == CIGateExitCode.BUDGET_EXCEEDED:
        console.print(
            f"[bold yellow]BUDGET EXCEEDED: Execution cost reached budget limit (Exit code {int(result.exit_code)})[/bold yellow]"
        )
    elif result.exit_code == CIGateExitCode.INFRA_ERROR:
        console.print(
            f"[bold red]INFRA ERROR: Infrastructure or sandbox connection failure (Exit code {int(result.exit_code)})[/bold red]"
        )

    raise typer.Exit(code=int(result.exit_code))
