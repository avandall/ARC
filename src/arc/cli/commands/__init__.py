"""ARC CLI Commands Package.

Subcommands:
    catalog: Commands for reviewing, listing, and approving candidate invariants.
    debug: Local reverse-proxy debugger for capturing and inspecting agent traces.
    gate: CI/CD Quality Gate evaluation with POSIX exit codes (0/1/2/3).
    incidents: Production incident tracking and escaped bug classification.
    init: Interactive setup wizard and configuration manager.
    minimize: Delta-Debugging (ddmin) minimization for bug reproducer YAMLs.
    repro: Deterministic replay and diagnostics for minimal bug reproducers.
"""

from __future__ import annotations

from arc.cli.commands.catalog import catalog_app
from arc.cli.commands.chaos_hub import list_incident_files, run_chaos_hub_menu
from arc.cli.commands.debug import debug_command
from arc.cli.commands.gate import gate_command
from arc.cli.commands.incidents import incidents_app
from arc.cli.commands.init import (
    init_app,
    init_command,
    run_edit_config_wizard,
    run_init_wizard,
)
from arc.cli.commands.minimize import minimize_command
from arc.cli.commands.repro import repro_command

__all__ = [
    "catalog_app",
    "debug_command",
    "gate_command",
    "incidents_app",
    "init_app",
    "init_command",
    "list_incident_files",
    "minimize_command",
    "repro_command",
    "run_chaos_hub_menu",
    "run_edit_config_wizard",
    "run_init_wizard",
]
