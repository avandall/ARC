"""Unit tests for CI Gate Engine exit codes (0/1/2/3) (TASK-P4-001)."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from arc.cli.main import app
from arc.execution.fork_engine.gate_evaluator import (
    CIGateExitCode,
    GateEvaluationResult,
    GateEvaluator,
    check_wilson_overlap,
)
from arc.execution.fork_engine.orchestrator import ForkRunResult

runner = CliRunner()


def test_arc_gate_clean_run_returns_exit_0() -> None:
    """Happy Path 1: Runs 'arc gate --profile smoke' on trace with no critical violations.

    Command prints summary and exits with code 0 (PASS).
    """
    mock_run_result = ForkRunResult(
        run_id="run_clean",
        status="success",
        k=3,
        n_valid=3,
        n_min=3,
        total_cost_usd=0.03,
        violations={},
    )

    with patch.object(GateEvaluator, "evaluate") as mock_eval:
        mock_eval.return_value = GateEvaluationResult(
            exit_code=CIGateExitCode.SUCCESS,
            status="PASS",
            profile="smoke",
            k=3,
            reason="No critical violations detected",
            total_cost_usd=0.03,
            run_result=mock_run_result,
        )

        result = runner.invoke(app, ["gate", "--profile", "smoke"])
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "Exit Code" in result.output


def test_arc_gate_critical_violation_returns_exit_1() -> None:
    """Happy Path 2: Runs 'arc gate' detecting critical invariant violation (Wilson CI non-overlapping).

    Command prints violation details and exits with code 1 (FAIL).
    """
    mock_violations = {
        "INV-CRITICAL-001": {
            "hits": 15,
            "n_valid": 20,
            "violation_rate": 0.75,
            "wilson_ci": [0.533, 0.888],
            "severity": "critical",
            "overlaps_baseline": False,
        }
    }
    mock_run_result = ForkRunResult(
        run_id="run_critical_fail",
        status="success",
        k=20,
        n_valid=20,
        n_min=12,
        total_cost_usd=0.20,
        violations=mock_violations,
    )

    with patch.object(GateEvaluator, "evaluate") as mock_eval:
        mock_eval.return_value = GateEvaluationResult(
            exit_code=CIGateExitCode.CRITICAL_VIOLATION,
            status="FAIL",
            profile="full",
            k=20,
            reason="Confirmed critical invariant violation detected (Wilson CI does not overlap baseline)",
            violations=mock_violations,
            total_cost_usd=0.20,
            run_result=mock_run_result,
        )

        result = runner.invoke(app, ["gate", "--profile", "full"])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "INV-CRITICAL-001" in result.output


def test_arc_gate_budget_exceeded_returns_exit_2() -> None:
    """Edge Case 1: Runs 'arc gate --budget-usd 0.05' exceeding cost threshold during replay.

    Command prints warning and exits with code 2 (BUDGET EXCEEDED).
    """
    mock_run_result = ForkRunResult(
        run_id="run_budget_exceeded",
        status="budget_exceeded",
        k=3,
        n_valid=1,
        n_min=3,
        n_budget=2,
        reason="budget_usd exceeded (0.06 > 0.05)",
        total_cost_usd=0.06,
    )

    with patch.object(GateEvaluator, "evaluate") as mock_eval:
        mock_eval.return_value = GateEvaluationResult(
            exit_code=CIGateExitCode.BUDGET_EXCEEDED,
            status="BUDGET_EXCEEDED",
            profile="smoke",
            k=3,
            reason="budget_usd exceeded (0.06 > 0.05)",
            total_cost_usd=0.06,
            run_result=mock_run_result,
        )

        result = runner.invoke(app, ["gate", "--profile", "smoke", "--budget-usd", "0.05"])
        assert result.exit_code == 2
        assert "BUDGET EXCEEDED" in result.output


def test_arc_gate_infra_docker_failure_returns_exit_3() -> None:
    """Edge Case 2: Simulates Docker daemon connection failure (ConnectionRefusedError).

    GateEvaluator catches infrastructure error, command prints diagnostic info and exits with code 3 (INFRA ERROR).
    """
    evaluator = GateEvaluator(profile="smoke")

    def mock_infra_runner() -> ForkRunResult:
        raise ConnectionRefusedError("Docker daemon not reachable at unix:///var/run/docker.sock")

    eval_result = evaluator.evaluate(orchestrator_runner=mock_infra_runner)
    assert eval_result.exit_code == CIGateExitCode.INFRA_ERROR
    assert eval_result.status == "INFRA_ERROR"
    assert "Docker daemon not reachable" in eval_result.reason

    with patch.object(GateEvaluator, "evaluate") as mock_eval:
        mock_eval.return_value = eval_result
        result = runner.invoke(app, ["gate", "--profile", "smoke"])
        assert result.exit_code == 3
        assert "INFRA ERROR" in result.output


def test_gate_evaluator_direct_logic() -> None:
    """Direct verification of GateEvaluator profiles and Wilson overlap math."""
    eval_smoke = GateEvaluator(profile="smoke")
    assert eval_smoke.k == 3

    eval_full = GateEvaluator(profile="full")
    assert eval_full.k == 20

    # Test Wilson interval overlap logic
    assert check_wilson_overlap([0.1, 0.4], [0.3, 0.6]) is True
    assert check_wilson_overlap([0.5, 0.8], [0.0, 0.1]) is False
