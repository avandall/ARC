"""Integration tests for Parallel Fork-Replay Engine & Wilson Score CI (TASK-P2-003)."""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

# Add execution/fork-engine directory to sys.path
sys.path.insert(0, os.path.abspath("execution/fork-engine"))

from fault_catalog import FaultSpec, FaultType
from orchestrator import ForkOrchestrator
from stats import calculate_wilson_score, compute_n_min, compute_n_valid


def test_fork_orchestrator_runs_k_branches_in_parallel() -> None:
    """Happy Path 1: Launches K=20 parallel branches from fork point with timeout_after_commit.

    Results in 20 independent branches running, collecting violation results and computing
    a valid 95% Wilson Score Interval.
    """
    orchestrator = ForkOrchestrator(k=20, max_workers=10)
    fault_spec = FaultSpec(
        at_step=7,
        fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
        target_tool="issue_refund",
        params={"delay_ms": 15000},
    )

    def custom_branch_executor(branch_id: int, spec: FaultSpec) -> dict[str, Any]:
        # Simulate 14 violations out of 20 runs
        has_violation = branch_id < 14
        return {
            "branch_id": branch_id,
            "status": "success",
            "fault_applied": spec.to_dict(),
            "violations": ["INV-PAY-002"] if has_violation else [],
            "cost_usd": 0.02,
            "tokens": 100,
            "duration_ms": 120,
        }

    result = orchestrator.run_fork(fault_spec=fault_spec, branch_executor=custom_branch_executor)

    assert result.k == 20
    assert result.n_valid == 20
    assert result.n_min == 12
    assert result.status == "completed"
    assert len(result.branch_results) == 20

    assert "INV-PAY-002" in result.violations
    v_stat = result.violations["INV-PAY-002"]
    assert v_stat["hits"] == 14
    assert v_stat["n_valid"] == 20
    assert v_stat["violation_rate"] == 0.70
    assert len(v_stat["wilson_ci"]) == 2
    assert 0.45 <= v_stat["wilson_ci"][0] <= 0.50
    assert 0.85 <= v_stat["wilson_ci"][1] <= 0.90


def test_wilson_score_confidence_interval_math() -> None:
    """Happy Path 2: Verifies Wilson Score calculation with 7 violations out of 20 valid samples (p=0.35).

    Result: Confidence interval returned matches mathematical formula [0.185, 0.576] (approx).
    """
    ci_lower, ci_upper = calculate_wilson_score(violations=7, n_valid=20, confidence=0.95)

    assert ci_lower == pytest.approx(0.185, abs=0.01)
    assert ci_upper == pytest.approx(0.576, abs=0.01)


def test_budget_enforcer_aborts_excessive_runs() -> None:
    """Edge Case 1: Configured budget_usd=1.0. Simulates cost per branch of $0.30.

    After 3 branches complete (total cost $0.90), 4th branch exceeds threshold $1.0 ($1.20 total).
    Budget enforcer aborts remaining branches and updates run status to budget_exceeded.
    """
    orchestrator = ForkOrchestrator(k=10, budget_usd=1.0, max_workers=1)
    fault_spec = FaultSpec(
        at_step=5,
        fault_type=FaultType.HTTP_500,
        target_tool="issue_refund",
    )

    def expensive_branch_executor(branch_id: int, spec: FaultSpec) -> dict[str, Any]:
        return {
            "branch_id": branch_id,
            "status": "success",
            "violations": ["INV-PAY-001"],
            "cost_usd": 0.30,
            "tokens": 500,
            "duration_ms": 200,
        }

    result = orchestrator.run_fork(fault_spec=fault_spec, branch_executor=expensive_branch_executor)

    assert result.status == "budget_exceeded"
    assert result.reason is not None
    assert "budget_usd exceeded" in result.reason or result.reason == "budget_exceeded"
    assert result.total_cost_usd >= 1.0
    assert result.n_budget > 0


def test_insufficient_valid_samples_returns_inconclusive() -> None:
    """Edge Case 2: Out of K=20 branches, 10 branches are aborted due to cassette_miss (N_valid = 10 < N_min = 12).

    Fork Engine refuses pass/fail conclusion and returns status inconclusive with reason insufficient_valid_samples.
    """
    orchestrator = ForkOrchestrator(k=20, max_workers=5)
    fault_spec = FaultSpec(
        at_step=3,
        fault_type=FaultType.BAD_SCHEMA,
        target_tool="get_user",
    )

    def cassette_miss_branch_executor(branch_id: int, spec: FaultSpec) -> dict[str, Any]:
        # 10 branches succeed, 10 fail with cassette_miss
        is_miss = branch_id >= 10
        if is_miss:
            return {
                "branch_id": branch_id,
                "status": "cassette_miss",
                "violations": [],
                "cost_usd": 0.0,
                "tokens": 0,
                "duration_ms": 10,
            }
        return {
            "branch_id": branch_id,
            "status": "success",
            "violations": ["INV-SCHEMA-001"],
            "cost_usd": 0.01,
            "tokens": 50,
            "duration_ms": 100,
        }

    result = orchestrator.run_fork(fault_spec=fault_spec, branch_executor=cassette_miss_branch_executor)

    assert result.status == "inconclusive"
    assert result.reason == "insufficient_valid_samples"
    assert result.n_miss == 10
    assert result.n_valid == 10
    assert result.n_min == 12
    assert compute_n_valid(20, n_miss=10) == 10
    assert compute_n_min(20) == 12
    assert result.violations == {}
