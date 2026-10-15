"""Unit and integration tests for wired components across ARC.

Verifies:
1. `arc repro --generate-test` writes test file in tests/regression/
2. `arc minimize` runs delta debugging on reproducer YAML
3. `arc gate --trace` loads trace and runs sandbox branch execution
4. `LocalDebuggerProxy` simulates reproducer faults and health status
5. `MockDatabase` records mutations in effect ledger and supports chaos faults
6. `push_trace_to_collector` SDK integration
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from arc.cli.main import app
from arc.cli.proxy.debugger_proxy import LocalDebuggerProxy
from arc.execution.tool_models.database_domain.mock_database import MockDatabase
from arc.sdk.interceptor import push_trace_to_collector, trace_agent

runner = CliRunner()


@pytest.fixture(autouse=True)
def cleanup_proxies() -> Any:
    LocalDebuggerProxy.stop_all()
    yield
    LocalDebuggerProxy.stop_all()


# ── 1. arc repro --generate-test ─────────────────────────────────────────────

def test_repro_with_generate_test_flag(tmp_path: Path) -> None:
    """`arc repro --generate-test` executes sandbox and generates pytest file."""
    repro_file = tmp_path / "arc-repro-test.yaml"
    out_dir = tmp_path / "regression_tests"
    repro_data = {
        "trace": "trace_test_gen",
        "violated": "INV-TEST-001",
        "determinism_level": "L1",
        "reproduce_rate": 1.0,
        "faults": [{"at_step": 1, "type": "timeout_after_commit", "tool": "issue_refund"}],
    }
    with open(repro_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(repro_data, f)

    res = runner.invoke(
        app,
        ["repro", str(repro_file), "--generate-test", "--test-output-dir", str(out_dir)],
    )

    assert res.exit_code == 0
    assert "Regression Test Generated" in res.output
    gen_file = out_dir / "test_arc_regression_test.py"
    assert gen_file.exists()
    assert "test_arc_regression_test" in gen_file.read_text(encoding="utf-8")


# ── 2. arc minimize CLI ──────────────────────────────────────────────────────

def test_minimize_command_runs_ddmin(tmp_path: Path) -> None:
    """`arc minimize` reads reproducer with 3 faults and outputs minimized YAML."""
    repro_file = tmp_path / "repro-noisy.yaml"
    out_min_file = tmp_path / "repro-minimized.yaml"
    repro_data = {
        "trace": "trace_minimize_test",
        "violated": "INV-IDEM-001",
        "determinism_level": "L1",
        "reproduce_rate": 1.0,
        "faults": [
            {"at_step": 1, "type": "duplicate_action", "tool": "issue_refund"},
            {"at_step": 2, "type": "latency_spike", "tool": "lookup"},
            {"at_step": 3, "type": "latency_spike", "tool": "send_email"},
        ],
    }
    with open(repro_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(repro_data, f)

    res = runner.invoke(app, ["minimize", str(repro_file), "--output", str(out_min_file)])

    assert res.exit_code == 0
    assert "Delta-Debugging Reduction Summary" in res.output
    assert out_min_file.exists()
    with open(out_min_file, "r", encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    assert len(saved["faults"]) <= 3


# ── 3. arc gate with trace ───────────────────────────────────────────────────

def test_gate_command_with_trace_file(tmp_path: Path) -> None:
    """`arc gate --trace` reads trace file and executes sandbox branch executor."""
    trace_file = tmp_path / "trace-sample.json"
    trace_data = {
        "trace_id": "trace_sample_123",
        "violated_invariant": "INV-PAY-002",
        "steps": [
            {
                "step_id": 1,
                "request": {"tool": "issue_refund", "args": {"order_id": "8842", "amount": 45.99}},
                "response": {"status": "ok"},
            }
        ],
    }
    with open(trace_file, "w", encoding="utf-8") as f:
        json.dump(trace_data, f)

    res = runner.invoke(
        app,
        ["gate", "--trace", str(trace_file), "--profile", "smoke"],
    )

    # Gate runs evaluation
    assert "ARC CI Gate Summary" in res.output
    assert res.exit_code in (0, 1, 2, 3)


# ── 4. LocalDebuggerProxy fault injection ─────────────────────────────────────

def test_local_debugger_proxy_fault_injection(tmp_path: Path) -> None:
    """LocalDebuggerProxy loads reproducer faults and simulates HTTP 504 timeout."""
    import urllib.request
    repro_file = tmp_path / "repro-proxy.yaml"
    repro_data = {
        "trace": "trace_proxy_test",
        "violated": "INV-001",
        "faults": [{"at_step": 1, "type": "timeout_after_commit", "tool": "issue_refund"}],
    }
    with open(repro_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(repro_data, f)

    proxy = LocalDebuggerProxy(repro_file=str(repro_file), requested_port=8199)
    bound_port, _ = proxy.start()

    try:
        # Check health endpoint
        req_health = urllib.request.Request(f"http://127.0.0.1:{bound_port}/healthz")
        with urllib.request.urlopen(req_health, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "healthy"
            assert data["faults_configured"] == 1

        # Post request at step 1 -> receives simulated 504 Gateway Timeout
        req_post = urllib.request.Request(
            f"http://127.0.0.1:{bound_port}/api/refund",
            data=b'{"order_id": "8842"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req_post, timeout=2.0)
            pytest.fail("Expected HTTP 504 from debugger proxy")
        except urllib.error.HTTPError as err:
            assert err.code == 504
    finally:
        proxy.stop()


# ── 5. MockDatabase tool model ────────────────────────────────────────────────

def test_mock_database_operations_and_effects() -> None:
    """MockDatabase traps mutations, returns rows for select, and records effects."""
    db = MockDatabase()

    # Read query
    select_res = db.handle({"action": "select", "table": "orders"})
    assert select_res["status"] == "ok"
    assert len(select_res["rows"]) == 1

    # Mutation query
    insert_res = db.handle({
        "action": "insert",
        "table": "orders",
        "query": "INSERT INTO orders VALUES ('9999', 'pending', 1000)",
    })
    assert insert_res["status"] == "ok"
    assert insert_res["affected_rows"] == 1

    effects = db.to_effect_ledger_entries()
    assert len(effects) == 1
    assert effects[0]["type"] == "database.mutation"
    assert effects[0]["resource"] == "table:orders"

    # Cloned instance state isolation
    cloned_db = db.clone_fresh_state()
    assert len(cloned_db.effects) == 1
    cloned_db.handle({"action": "delete", "table": "orders", "query": "DELETE FROM orders"})
    assert len(cloned_db.to_effect_ledger_entries()) == 2
    assert len(db.to_effect_ledger_entries()) == 1, "Cloned DB mutations must not mutate original"


# ── 6. SDK Collector Push ────────────────────────────────────────────────────

def test_push_trace_to_collector() -> None:
    """SDK push_trace_to_collector sends POST request to collector URL."""
    fake_trace = {"trace_id": "trace_test_sdk_push", "steps": []}

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 202
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success = push_trace_to_collector(fake_trace, collector_url="http://localhost:8080")
        assert success is True
        mock_urlopen.assert_called_once()


def test_trace_agent_triggers_collector_push_on_exit() -> None:
    """@trace_agent with collector_url pushes trace on exit."""
    with patch("arc.sdk.interceptor.push_trace_to_collector") as mock_push:
        mock_push.return_value = True

        @trace_agent(name="test_collector_agent", collector_url="http://mock-collector:8080")
        def sample_agent() -> str:
            return "done"

        res = sample_agent()
        assert res == "done"
        assert mock_push.called is True
        args, _ = mock_push.call_args
        assert args[0]["agent"]["name"] == "test_collector_agent"
        assert args[1] == "http://mock-collector:8080"
