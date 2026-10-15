"""Integration tests for F3: ForkOrchestrator integration with InvariantEvaluator.

Verifies that when branch executors return raw effects, the orchestrator evaluates
invariants and populates violations automatically and deterministically.
"""

from __future__ import annotations

from typing import Any

from arc.execution.fork_engine.fault_catalog import FaultSpec, FaultType
from arc.execution.fork_engine.orchestrator import ForkOrchestrator


def test_orchestrator_evaluates_branch_effects_into_violations() -> None:
    """F3: Branch returning raw effects causes InvariantEvaluator to detect violations."""
    catalog = [
        {
            "id": "INV-LIMIT-100",
            "statement": "Total refund per step cannot exceed $100",
            "category": "safety",
            "check": "all(e.delta.get('amount', 0) <= 100 for e in effects)",
            "severity": "critical",
        }
    ]

    orchestrator = ForkOrchestrator(k=10, max_workers=5, invariant_catalog=catalog)
    fault_spec = FaultSpec(at_step=1, fault_type=FaultType.HTTP_500, target_tool="issue_refund")

    def effect_branch_executor(branch_id: int, spec: FaultSpec) -> dict[str, Any]:
        # Branch 0 to 6 exceed limit ($150), branch 7 to 9 remain under ($50)
        amount = 150.0 if branch_id < 7 else 50.0
        effects = [
            {
                "effect_id": f"eff_{branch_id}",
                "step_id": 1,
                "type": "issue_refund",
                "resource": "order:8842",
                "delta": {"amount": amount},
                "reversible": False,
            }
        ]
        return {
            "branch_id": branch_id,
            "status": "success",
            "fault_applied": spec.to_dict(),
            "effects": effects,
            "cost_usd": 0.01,
            "tokens": 50,
            "duration_ms": 100,
        }

    result = orchestrator.run_fork(fault_spec=fault_spec, branch_executor=effect_branch_executor)

    assert result.status == "completed"
    assert result.n_valid == 10
    assert "INV-LIMIT-100" in result.violations
    v_info = result.violations["INV-LIMIT-100"]
    assert v_info["hits"] == 7
    assert v_info["violation_rate"] == 0.70
    assert v_info["severity"] == "critical"


def test_quarantined_invariant_does_not_register_as_blocking_violation() -> None:
    """F3: Quarantined invariant does not block or appear in blocking violations."""
    catalog = [
        {
            "id": "INV-QUARANTINED",
            "statement": "Flaky check in quarantine",
            "category": "safety",
            "check": "False",  # always violates if evaluated
            "status": "quarantined",
            "severity": "critical",
        }
    ]

    orchestrator = ForkOrchestrator(k=5, max_workers=2, invariant_catalog=catalog)
    fault_spec = FaultSpec(at_step=1, fault_type=FaultType.HTTP_500)

    def simple_executor(branch_id: int, spec: FaultSpec) -> dict[str, Any]:
        return {
            "branch_id": branch_id,
            "status": "success",
            "effects": [{"type": "some_tool", "delta": {}}],
            "cost_usd": 0.01,
            "tokens": 10,
            "duration_ms": 50,
        }

    result = orchestrator.run_fork(fault_spec=fault_spec, branch_executor=simple_executor)

    # Invariant is quarantined, so should_block_ci returns False
    # and it does not count as a blocking violation
    assert "INV-QUARANTINED" not in result.violations
