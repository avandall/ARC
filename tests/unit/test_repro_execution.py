"""Unit tests for F4: arc repro sandbox execution and verification.

Verifies that `arc repro` actually runs the fault injection through SandboxRunner,
recording effects and outputting the sandbox execution result panel.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from arc.cli.main import app

runner = CliRunner()


def test_cli_repro_executes_sandbox_and_displays_panel(tmp_path: Path) -> None:
    """F4: `arc repro` triggers real sandbox execution panel in terminal."""
    repro_file = tmp_path / "test-repro.yaml"
    repro_data = {
        "trace": "test_trace_123",
        "violated": "INV-TEST-001",
        "check": "len(effects) == 0",
        "determinism_level": "L1",
        "reproduce_rate": 1.0,
        "faults": [
            {
                "at_step": 1,
                "type": "duplicate_action",
                "tool": "issue_refund",
            }
        ],
    }
    with open(repro_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(repro_data, f)

    result = runner.invoke(app, ["repro", str(repro_file)])

    assert result.exit_code == 0
    # Check that the sandbox execution section was reached and printed
    assert "Sandbox Execution Result" in result.output
    assert "Effects Recorded" in result.output
    assert "Faults Applied" in result.output
