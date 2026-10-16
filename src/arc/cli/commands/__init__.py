"""ARC CLI Commands Package.

Subcommands:
    catalog: Commands for reviewing, listing, and approving candidate invariants.
    debug: Local reverse-proxy debugger for capturing and inspecting agent traces.
    gate: CI/CD Quality Gate evaluation with POSIX exit codes (0/1/2/3).
    incidents: Production incident tracking and escaped bug classification.
    minimize: Delta-Debugging (ddmin) minimization for bug reproducer YAMLs.
    repro: Deterministic replay and diagnostics for minimal bug reproducers.
"""

from __future__ import annotations

from arc.cli.commands.catalog import catalog_app
from arc.cli.commands.debug import debug_command
from arc.cli.commands.gate import gate_command
from arc.cli.commands.incidents import incidents_app
from arc.cli.commands.minimize import minimize_command
from arc.cli.commands.repro import repro_command

__all__ = [
    "catalog_app",
    "debug_command",
    "gate_command",
    "incidents_app",
    "minimize_command",
    "repro_command",
]
