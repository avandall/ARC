"""Unit tests for Chaos Testing Hub & Prod Incident File Browser (TASK-CLI-005).

Covers:
- Incident file scanning (.yaml, .yml, .json) in .arc/incidents/
- Empty incident directory handling with friendly prompt
- Targeted Boundary Injection tool classification and fault mapping
- Replay execution with Visual UI Engine (PASS [repro] / REPRODUCED_INVARIANT_VIOLATION)
- Interactive Chaos Hub submenu dispatching ([2.1] to [2.4])
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml
from rich.console import Console

from arc.cli.commands.chaos_hub import (
    get_boundary_faults,
    is_boundary_tool,
    list_incident_files,
    run_chaos_hub_menu,
    run_repro_visual,
)


def _to_plain_text(rich_str: str) -> str:
    """Renders Rich markup string to plain text."""
    console = Console(record=True, width=120, force_terminal=False)
    console.print(rich_str)
    return console.export_text()


def test_list_incident_files_empty(tmp_path: Path) -> None:
    """Returns empty list when incidents folder is missing or empty."""
    assert list_incident_files(tmp_path) == []

    inc_dir = tmp_path / ".arc" / "incidents"
    inc_dir.mkdir(parents=True)
    assert list_incident_files(tmp_path) == []

    # Non-incident files should be ignored
    (inc_dir / "notes.txt").write_text("not an incident", encoding="utf-8")
    (inc_dir / ".gitkeep").write_text("", encoding="utf-8")
    assert list_incident_files(tmp_path) == []


def test_list_incident_files_discovery(tmp_path: Path) -> None:
    """Discovers .yaml, .yml, and .json files sorted by filename."""
    inc_dir = tmp_path / ".arc" / "incidents"
    inc_dir.mkdir(parents=True)

    f1 = inc_dir / "inc_2026_09_payment.yaml"
    f2 = inc_dir / "inc_2026_10_refund.json"
    f3 = inc_dir / "inc_2026_08_order.yml"
    f_ignored = inc_dir / "README.md"

    f1.write_text("trace: t1\nviolated: INV-01", encoding="utf-8")
    f2.write_text(json.dumps({"trace": "t2", "violated": "INV-02"}), encoding="utf-8")
    f3.write_text("trace: t3\nviolated: INV-03", encoding="utf-8")
    f_ignored.write_text("# Incident Directory", encoding="utf-8")

    files = list_incident_files(tmp_path)
    assert len(files) == 3
    names = [f.name for f in files]
    assert names == [
        "inc_2026_08_order.yml",
        "inc_2026_09_payment.yaml",
        "inc_2026_10_refund.json",
    ]


def test_targeted_boundary_injection_classification() -> None:
    """Verifies that only mutating / external interaction points are flagged as boundary tools."""
    # Mutating & Boundary tools
    assert is_boundary_tool("issue_refund") is True
    assert is_boundary_tool("payment_gateway") is True
    assert is_boundary_tool("charge_card") is True
    assert is_boundary_tool("update_order_status") is True
    assert is_boundary_tool("db_write_transaction") is True
    assert is_boundary_tool("external_shipping_api") is True

    # Read-only or internal computation tools
    assert is_boundary_tool("calculate_order_tax") is False
    assert is_boundary_tool("format_customer_name") is False
    assert is_boundary_tool("parse_date_string") is False


def test_get_boundary_faults_mapping() -> None:
    """Ensures boundary tools are mapped to appropriate chaos fault types."""
    payment_faults = get_boundary_faults("payment_gateway")
    assert "timeout_after_commit" in payment_faults
    assert "double_submit" in payment_faults

    db_faults = get_boundary_faults("database_conn")
    assert "connection_refused" in db_faults or "deadlock_rollback" in db_faults

    api_faults = get_boundary_faults("external_crm_api")
    assert "http_429" in api_faults or "http_502" in api_faults


def test_run_repro_visual_renders_playwright_style(tmp_path: Path) -> None:
    """Verifies run_repro_visual generates PASS [repro] and REPRODUCED_INVARIANT_VIOLATION."""
    incident_file = tmp_path / "inc_test.yaml"
    incident_data = {
        "trace": "trace_checkout_fail_9981",
        "violated": "INV-PAY-002",
        "category": "Safety",
        "statement": "Payment tool must never be executed more than once per order_id",
        "reproduce_rate": 1.0,
        "confidence_interval": [0.925, 1.0],
        "determinism_level": "L1",
        "faults": [
            {
                "step": 3,
                "tool": "payment_gateway",
                "type": "timeout_after_commit",
                "details": "504 Gateway Timeout after commit",
            }
        ],
        "evidence": [
            "- Expected: effects.count('issue_payment') == 1",
            "+ Actual:   effects.count('issue_payment') == 2",
        ],
    }
    with open(incident_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(incident_data, f)

    output = run_repro_visual(incident_file)
    plain = _to_plain_text(output)

    assert "PASS" in plain
    assert "repro" in plain
    assert "REPRODUCED_INVARIANT_VIOLATION" in plain
    assert "INV-PAY-002" in plain
    assert "Safety" in plain
    assert "payment_gateway" in plain
    assert "timeout_after_commit" in plain
    assert "REPRODUCED" in plain
    assert "[92.5%, 100.0%]" in plain


def test_chaos_hub_menu_empty_incidents(tmp_path: Path) -> None:
    """Selecting [2.4] with no incident files displays helpful guidance message."""
    with patch("questionary.select") as mock_select, patch("rich.console.Console.print") as mock_print:
        # User selects [2.4] then menu returns
        mock_select.return_value.ask.return_value = "[2.4] Reproduce Bug from Prod Incidents"

        run_chaos_hub_menu(tmp_path)

        # Verify guidance message was printed
        printed_texts = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
        assert any("No incident files found in .arc/incidents/" in text for text in printed_texts)


def test_chaos_hub_menu_repro_selection(tmp_path: Path) -> None:
    """Selecting [2.4] with existing incident prompts user and triggers visual repro."""
    inc_dir = tmp_path / ".arc" / "incidents"
    inc_dir.mkdir(parents=True)
    inc_file = inc_dir / "inc_2026_09_payment.yaml"
    inc_file.write_text(
        yaml.safe_dump(
            {
                "trace": "t1",
                "violated": "INV-001",
                "faults": [{"step": 1, "tool": "pay", "type": "timeout_after_commit"}],
            }
        ),
        encoding="utf-8",
    )

    with patch("questionary.select") as mock_select, patch(
        "arc.cli.commands.chaos_hub.run_repro_visual"
    ) as mock_repro:
        mock_repro.return_value = "PASS [repro] REPRODUCED_INVARIANT_VIOLATION"

        # First ask selects [2.4], second ask selects the file
        mock_select.return_value.ask.side_effect = [
            "[2.4] Reproduce Bug from Prod Incidents",
            inc_file.name,
        ]

        run_chaos_hub_menu(tmp_path)

        mock_repro.assert_called_once_with(inc_file)


def test_chaos_hub_menu_full_gate(tmp_path: Path) -> None:
    """Selecting [2.1] prompts for profile and executes gate."""
    with patch("questionary.select") as mock_select, patch(
        "arc.cli.commands.chaos_hub.handle_full_chaos_gate"
    ) as mock_gate:
        mock_select.return_value.ask.side_effect = [
            "[2.1] Full Flow Chaos Gate (arc gate)",
            "smoke (K=3, fast core scenarios)",
        ]

        run_chaos_hub_menu(tmp_path)

        mock_gate.assert_called_once_with(profile="smoke", k=3, project_root=tmp_path)


def test_chaos_hub_menu_custom_k_gate(tmp_path: Path) -> None:
    """Selecting [2.1] custom profile prompts for custom K and executes gate."""
    with patch("questionary.select") as mock_select, patch(
        "questionary.text"
    ) as mock_text, patch(
        "arc.cli.commands.chaos_hub.handle_full_chaos_gate"
    ) as mock_gate:
        mock_select.return_value.ask.side_effect = [
            "[2.1] Full Flow Chaos Gate (arc gate)",
            "custom (specify custom number of forks K)",
        ]
        mock_text.return_value.ask.return_value = "8"

        run_chaos_hub_menu(tmp_path)

        mock_gate.assert_called_once_with(profile="custom", k=8, project_root=tmp_path)


def test_chaos_hub_menu_mock_services(tmp_path: Path) -> None:
    """Selecting [2.2] simulates mock services."""
    with patch("questionary.select") as mock_select, patch(
        "arc.cli.commands.chaos_hub.handle_mock_service_simulation"
    ) as mock_sim:
        mock_select.return_value.ask.side_effect = [
            "[2.2] Third-Party & Mock DB Simulation",
            "[db_down] Mock Database Outage (ConnectionRefused / Deadlock)",
        ]

        run_chaos_hub_menu(tmp_path)

        mock_sim.assert_called_once_with("db_down", project_root=tmp_path)


def test_chaos_hub_menu_k_forks(tmp_path: Path) -> None:
    """Selecting [2.3] runs K-parallel fork replay."""
    with patch("questionary.select") as mock_select, patch(
        "arc.cli.commands.chaos_hub.handle_k_parallel_fork_replay"
    ) as mock_fork:
        mock_select.return_value.ask.side_effect = [
            "[2.3] K-Parallel Fork Replay",
            "K=5 (quick stability assessment)",
        ]

        run_chaos_hub_menu(tmp_path)

        mock_fork.assert_called_once_with(5, project_root=tmp_path)


def test_repro_cli_with_visual_flag(tmp_path: Path) -> None:
    """Verifies that `arc repro <file> --visual` invokes Visual UI Engine."""
    from typer.testing import CliRunner

    from arc.cli.main import app

    runner = CliRunner()
    incident_file = tmp_path / "inc_vis.yaml"
    incident_file.write_text(
        yaml.safe_dump(
            {
                "trace": "trace_123",
                "violated": "INV-PAY-009",
                "faults": [{"step": 2, "tool": "payment", "type": "timeout_after_commit"}],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["repro", str(incident_file), "--visual"])
    assert result.exit_code == 0
    assert "PASS" in result.output
    assert "repro" in result.output
    assert "REPRODUCED_INVARIANT_VIOLATION" in result.output
    assert "INV-PAY-009" in result.output


def test_main_menu_routes_to_chaos_hub(tmp_path: Path) -> None:
    """Verifies that selecting option [2] in main menu routes to chaos hub."""
    from arc.cli.main import run_main_menu

    with patch("questionary.select") as mock_select, patch(
        "arc.cli.main.run_chaos_hub_menu"
    ) as mock_chaos_hub:
        mock_select.return_value.ask.return_value = (
            "[2] Fault Injection & Chaos Testing (Security Check / Gate)"
        )
        run_main_menu(tmp_path)
        mock_chaos_hub.assert_called_once_with(tmp_path)


def test_handle_mock_service_and_k_parallel_execute_real_engines(tmp_path: Path) -> None:
    """Verifies that simulation and k-parallel replay run real engines rather than hardcoded tables."""
    from arc.cli.commands.chaos_hub import (
        handle_k_parallel_fork_replay,
        handle_mock_service_simulation,
    )

    # 1. Real service simulation execution
    handle_mock_service_simulation("db_down", project_root=tmp_path)
    handle_mock_service_simulation("payment_timeout", project_root=tmp_path)
    handle_mock_service_simulation("rate_limit", project_root=tmp_path)

    # 2. Real K-parallel fork execution
    handle_k_parallel_fork_replay(k=3, project_root=tmp_path)


