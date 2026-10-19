"""ARC Main CLI Entrypoint with Smart State Detection (TASK-CLI-002).

Provides interactive onboarding on first run and quick-action menu on subsequent runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import questionary
import typer
from rich.console import Console
from rich.panel import Panel

from arc.cli.commands.catalog import catalog_app
from arc.cli.commands.chaos_hub import run_chaos_hub_menu
from arc.cli.commands.debug import debug_command
from arc.cli.commands.gate import gate_command
from arc.cli.commands.incidents import incidents_app
from arc.cli.commands.init import (
    init_app,
    run_edit_config_wizard,
    run_init_wizard,
)
from arc.cli.commands.minimize import minimize_command
from arc.cli.commands.repro import repro_command
from arc.cli.scaffold import is_arc_scaffold_initialized

import time

console = Console()


def print_banner() -> None:
    """Prints the stylish ARC large ASCII banner line-by-line with a snappy animation."""
    banner_lines = [
        "[bold cyan]  █████╗ ██████╗  ██████╗ [/bold cyan]",
        "[bold cyan] ██╔══██╗██╔══██╗██╔════╝ [/bold cyan]",
        "[bold cyan] ███████║██████╔╝██║      [/bold cyan]",
        "[bold cyan] ██╔══██║██╔══██╗██║      [/bold cyan]",
        "[bold cyan] ██║  ██║██║  ██║╚██████╗ [/bold cyan]",
        "[bold cyan] ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ [/bold cyan]",
        "[dim cyan]Autonomous Reliability & Chaos Engine[/dim cyan]",
    ]
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    for line in banner_lines:
        console.print(line)
        if is_tty:
            time.sleep(0.035)
    if is_tty:
        time.sleep(0.04)


app = typer.Typer(
    name="arc",
    help="ARC CLI - Autonomous Reliability & Chaos Engine",
    add_completion=False,
)

# Register subcommands
app.command("repro")(repro_command)
app.command("minimize")(minimize_command)
app.command("debug")(debug_command)
app.command("gate")(gate_command)
app.add_typer(init_app, name="init")
app.add_typer(catalog_app, name="catalog")
app.add_typer(incidents_app, name="incidents")


def run_setup_menu(project_root: Path) -> None:
    """Submenu for Setup & Instrumentation."""
    while True:
        try:
            choice = questionary.select(
                "Setup & Instrumentation:",
                choices=[
                    "[1.1] Edit Configuration",
                    "[1.2] Setup Tracing (@trace_agent & @trace_tool)",
                    "[1.3] Back to Main Menu",
                ],
            ).ask()

            if choice is None or choice == "[1.3] Back to Main Menu":
                return

            if choice == "[1.1] Edit Configuration":
                run_edit_config_wizard(project_root)
            elif choice == "[1.2] Setup Tracing (@trace_agent & @trace_tool)":
                mode = questionary.select(
                    "Tracing attachment mode:",
                    choices=[
                        "[1] Auto (AST Scanner & Interactive Diff Review)",
                        "[2] Manually (Guide & Examples)",
                        "[3] Back to Setup Menu",
                    ],
                ).ask()
                if mode is None or mode.startswith("[3]"):
                    continue

                if mode.startswith("[1]"):
                    from arc.cli.tracer.scanner import is_ignored_file, scan_file_for_tracing
                    from arc.cli.ui.diff import review_and_apply_candidates

                    py_files = [
                        p
                        for p in project_root.rglob("*.py")
                        if not is_ignored_file(p)
                    ]
                    all_cands = []
                    for pf in py_files:
                        all_cands.extend(scan_file_for_tracing(pf))

                    if not all_cands:
                        console.print("[green]✓ No uninstrumented agent or tool functions found.[/green]")
                    else:
                        console.print(f"[cyan]Found {len(all_cands)} tracing candidate(s). Starting review...[/cyan]")
                        applied = review_and_apply_candidates(all_cands, interactive=True)
                        console.print(f"[green]✓ Completed: {len(applied)} function(s) instrumented.[/green]")
                elif mode.startswith("[2]"):
                    console.print(
                        Panel.fit(
                            "[bold]Manual Tracing Setup Example:[/bold]\n\n"
                            "  from arc import trace_agent, trace_tool\n\n"
                            "  @trace_tool(name=\"database_lookup\")\n"
                            "  def lookup_record(id: str):\n"
                            "      return ...\n\n"
                            "  @trace_agent(name=\"primary_assistant\")\n"
                            "  def handle_message(msg: str):\n"
                            "      return ...",
                            title="Tracing Guide",
                            border_style="cyan",
                        )
                    )

            console.print("\n[dim]" + "─" * 70 + "[/dim]\n")
        except (StopIteration, KeyboardInterrupt):
            break


def run_main_menu(project_root: Path | None = None) -> bool:
    """Displays the interactive Main Menu for configured ARC projects.

    Returns True if an action was executed and the session should continue,
    or False if Exit was chosen or the menu was cancelled.
    """
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()

    try:
        action = questionary.select(
            "Select an action:",
            choices=[
                "[1] Setup & Instrumentation (Configure / Attach Tracing)",
                "[2] Fault Injection & Chaos Testing (Security Check / Gate)",
                "[3] Auto-Mine Invariants (Extract rules from Code / Schema / Postmortems)",
                "[4] Exit",
            ],
        ).ask()

        if action is None or action == "[4] Exit":
            console.print("[dim]Goodbye![/dim]")
            return False

        if action.startswith("[1]"):
            run_setup_menu(root)
        elif action.startswith("[2]"):
            run_chaos_hub_menu(root)
        elif action.startswith("[3]"):
            from arc.cli.commands.init import _trigger_quick_auto_mine
            console.print("[dim]Scanning schemas and source code for invariants...[/dim]")
            mined = _trigger_quick_auto_mine(root)
            console.print(f"[green]✓ Invariant mining complete: {mined} candidates recorded into catalog.[/green]")
            console.print("[cyan]Run [bold]arc catalog review[/bold] to inspect candidates.[/cyan]")

        console.print("\n[dim]" + "─" * 70 + "[/dim]\n")
        return True
    except (StopIteration, KeyboardInterrupt, EOFError):
        return False


def handle_smart_start(project_root: Path | None = None) -> None:
    """Smart state detection: first-time launch runs wizard, subsequent launch shows Main Menu."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    print_banner()

    if not is_arc_scaffold_initialized(root):
        run_init_wizard(root)
    else:
        console.print(
            Panel.fit(
                f"[bold]Project:[/bold] {root}  |  [bold]Config:[/bold] .arc/config.yaml [[green]Active[/green]]",
                title="[bold cyan]ARC Autonomous Reliability & Chaos Engine[/bold cyan]",
                border_style="cyan",
            )
        )
        while True:
            try:
                should_continue = run_main_menu(root)
                if not should_continue:
                    break
            except (StopIteration, KeyboardInterrupt, EOFError):
                break


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """ARC CLI Main Callback handling Smart State Detection."""
    if ctx.invoked_subcommand is None:
        if not sys.stdin.isatty():
            print_banner()
            root = Path.cwd().resolve()
            console.print(
                Panel.fit(
                    f"[bold]Project:[/bold] {root}\n"
                    f"[bold]Status:[/bold] {'Configured (.arc/config.yaml)' if is_arc_scaffold_initialized(root) else 'Uninitialized'}\n\n"
                    "[dim]Running in non-interactive environment. Use subcommands directly, e.g.:\n"
                    "  arc --help\n"
                    "  arc gate --profile smoke\n"
                    "  arc repro <spec_file>[/dim]",
                    title="[bold cyan]ARC CLI[/bold cyan]",
                    border_style="cyan",
                )
            )
            return
        handle_smart_start()


if __name__ == "__main__":
    app()
