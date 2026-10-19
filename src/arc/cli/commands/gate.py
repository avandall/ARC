"""ARC CLI `arc gate` command implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from arc.cli.commands.repro import find_trace_file
from arc.execution.fork_engine.gate_evaluator import CIGateExitCode, GateEvaluator

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
    actual_profile = profile if isinstance(profile, str) else str(getattr(profile, "default", "smoke"))
    actual_budget = budget_usd if isinstance(budget_usd, (int, float)) else getattr(budget_usd, "default", None)
    actual_trace = str(trace) if isinstance(trace, (str, Path)) else getattr(trace, "default", None)
    actual_ci_lower = float(baseline_ci_lower if isinstance(baseline_ci_lower, (int, float)) else getattr(baseline_ci_lower, "default", 0.0))
    actual_ci_upper = float(baseline_ci_upper if isinstance(baseline_ci_upper, (int, float)) else getattr(baseline_ci_upper, "default", 0.0))

    evaluator = GateEvaluator(
        profile=actual_profile,
        budget_usd=actual_budget,
        baseline_ci=(actual_ci_lower, actual_ci_upper),
    )

    cwd = Path.cwd()
    trace_ref = actual_trace or "trace_ci_gate"
    trace_file = find_trace_file(trace_ref, cwd) if actual_trace else None

    branch_executor = None
    fault_catalog = None

    if trace_file is not None and trace_file.exists():
        try:
            from arc.execution.fork_engine.fault_catalog import FaultCatalog, FaultSpec
            from arc.execution.sandbox_runner.cassette_player import CassettePlayer, CassetteRecord
            from arc.execution.sandbox_runner.runner import SandboxRunner

            trace_json = json.loads(trace_file.read_text(encoding="utf-8"))
            steps = trace_json.get("steps", [])
            cassette_records: list[CassetteRecord] = [
                CassetteRecord(
                    tool=str(s["request"]["tool"]),
                    request_args=s["request"].get("args", {}),
                    response=s.get("response", {"status": "ok"}),
                )
                for s in steps
                if isinstance(s.get("request"), dict) and "tool" in s["request"]
            ]
            cassette_player = CassettePlayer(records=cassette_records) if cassette_records else None

            # Look up target invariant from trace or default
            trace_inv = trace_json.get("violated_invariant") or trace_json.get("invariant") or "INV-GATE-001"
            target_inv: dict[str, Any] = {
                "id": str(trace_inv),
                "statement": "Tool executions must not produce unhandled mutations or errors",
                "category": "safety",
                "check": "len([e for e in effects if e.get('status') == 'error']) == 0",
                "severity": "critical",
            }

            fault_catalog = FaultCatalog()
            fault_catalog.add_fault(FaultSpec(at_step=1, fault_type="timeout_after_commit"))

            def _gate_branch_executor(branch_id: int, spec: FaultSpec) -> dict[str, Any]:
                runner = SandboxRunner()
                res = runner.run_with_faults(
                    fault_spec=[spec.to_dict()],
                    target_invariant=target_inv,
                    cassette_player=cassette_player,
                )
                violations = [res["violated_invariant"]] if not res.get("passed", True) else []
                return {
                    "branch_id": branch_id,
                    "status": "success",
                    "fault_applied": spec.to_dict(),
                    "violations": violations,
                    "effects": res.get("effects", []),
                    "cost_usd": 0.0,
                    "tokens": int(res.get("tokens", 0)),
                    "duration_ms": int(res.get("eval_result", {}).get("exec_time_ms", 0)),
                }

            branch_executor = _gate_branch_executor
            console.print(f"[dim]Loaded trace from: {trace_file.name} ({len(cassette_records)} steps)[/dim]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[dim yellow](Unable to construct branch executor from trace: {exc})[/dim yellow]")

    result = evaluator.evaluate(
        branch_executor=branch_executor,
        fault_catalog=fault_catalog,
        trace_id=trace,
    )

    table = Table(title=f"ARC CI Gate Summary [Profile: {profile.upper()}]")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Status", result.status)
    table.add_row("Exit Code", str(int(result.exit_code)))
    table.add_row("Profile", result.profile)
    table.add_row("K Branches", str(result.k))
    table.add_row("Reason", result.reason)

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
