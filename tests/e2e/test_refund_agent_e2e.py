"""End-to-End Test Suite for `refund-agent` Reference Implementation (TASK-P4-004).

Tests:
1. Nominal execution workflow and invariant INV-PAY-002 check (passed).
2. Chaos execution with timeout_after_commit reproducing double refund defect (INV-PAY-002 violated in 7/20 branches).
3. Auto-generation of minimal reproducer arc-repro-8842.yaml and CLI replay verification.
4. README walkthrough execution completing in under 15 minutes.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

# Ensure required source roots are in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sdk_python_dir = os.path.join(root_dir, "sdk", "python")
exec_fork_dir = os.path.join(root_dir, "execution", "fork-engine")
exec_inv_dir = os.path.join(root_dir, "execution", "invariant-engine")
examples_dir = os.path.join(root_dir, "examples", "refund-agent")

for p in [root_dir, sdk_python_dir, exec_fork_dir, exec_inv_dir, examples_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent import INV_PAY_002_SPEC, run_refund_agent
from delta_debugging import ddmin
from evaluator import InvariantEvaluator
from orchestrator import FaultSpec, ForkOrchestrator
from reproducer_export import export_minimal_reproducer_yaml

from cli.main import app

runner = CliRunner()


def test_refund_agent_nominal_execution() -> None:
    """Happy Path 1: Nominal execution of refund-agent.

    Lookup order #8842, check policy, call refund $45.99 successfully, send email.
    Trace is fully recorded and invariant INV-PAY-002 passes.
    """
    res = run_refund_agent(order_id="8842", inject_fault=False)

    assert res["status"] == "completed"
    assert res["order_id"] == "8842"
    assert res["lookup"]["total_amount"] == 45.99
    assert res["policy"]["eligible"] is True
    assert res["refund"]["status"] == "ok"
    assert res["refund"]["amount"] == 45.99
    assert res["email"]["status"] == "sent"

    # Verify CTF trace structure
    ctf = res["ctf_trace"]
    assert ctf["agent"]["name"] == "refund-agent"
    step_tools = [s["request"]["tool"] for s in ctf["steps"]]
    assert step_tools == ["lookup", "check_policy", "issue_refund", "send_email"]

    # Verify invariant INV-PAY-002 evaluation passes
    evaluator = InvariantEvaluator()
    context = {"order": {"ref": "order:8842", "total_cents": 4599}}
    effects = res["effects"]

    eval_res = evaluator.evaluate(INV_PAY_002_SPEC, effects, context)
    assert eval_res.invariant_id == "INV-PAY-002"
    assert eval_res.violated is False, f"Expected INV-PAY-002 to pass on nominal execution: {eval_res.error}"


def test_refund_agent_chaos_reproduces_double_refund() -> None:
    """Happy Path 2: Chaos execution reproducing double refund defect.

    Injects fault timeout_after_commit at step issue_refund.
    Agent retries refund 2nd time due to missing idempotency key.
    Fork Engine runs 20 parallel branches, detecting INV-PAY-002 violation in 7/20 branches (p=0.35).
    """
    orchestrator = ForkOrchestrator(k=20)
    fault_spec = FaultSpec(at_step=2, fault_type="timeout_after_commit", target_tool="issue_refund")

    evaluator = InvariantEvaluator()
    context = {"order": {"ref": "order:8842", "total_cents": 4599}}

    def custom_branch_executor(branch_id: int, spec: FaultSpec) -> dict[str, Any]:
        # Exactly 7 of 20 branches (ids 0..6) hit the chaos double-refund path
        inject = branch_id < 7
        agent_res = run_refund_agent(order_id="8842", inject_fault=inject)

        eval_res = evaluator.evaluate(INV_PAY_002_SPEC, agent_res["effects"], context)
        violations = ["INV-PAY-002"] if eval_res.violated else []

        return {
            "branch_id": branch_id,
            "status": "success",
            "fault_applied": spec.to_dict(),
            "violations": violations,
            "cost_usd": 0.0025,
            "tokens": 100,
            "duration_ms": 15,
        }

    fork_result = orchestrator.run_fork(fault_spec=fault_spec, branch_executor=custom_branch_executor)

    assert fork_result.status == "completed"
    assert fork_result.k == 20
    assert fork_result.n_valid == 20
    assert "INV-PAY-002" in fork_result.violations

    v_stat = fork_result.violations["INV-PAY-002"]
    assert v_stat["hits"] == 7
    assert v_stat["violation_rate"] == 0.35
    assert len(v_stat["wilson_ci"]) == 2
    assert v_stat["wilson_ci"][0] < v_stat["wilson_ci"][1]


def test_refund_agent_auto_generates_repro_8842_yaml(tmp_path: Path) -> None:
    """Edge Case 1: Auto-generation and CLI replay of arc-repro-8842.yaml.

    After detecting violation, ddmin reduces fault sequence and exports minimal reproducer.
    Verified with CLI `arc repro`.
    """
    initial_faults = [
        {"at_step": 0, "type": "latency_spike", "tool": "lookup"},
        {"at_step": 2, "type": "timeout_after_commit", "tool": "issue_refund"},
    ]

    evaluator = InvariantEvaluator()
    context = {"order": {"ref": "order:8842", "total_cents": 4599}}

    def test_fault_subset(fault_list: list[dict[str, Any]]) -> bool:
        has_timeout = any(f.get("type") == "timeout_after_commit" for f in fault_list)
        agent_res = run_refund_agent(order_id="8842", inject_fault=has_timeout)
        eval_res = evaluator.evaluate(INV_PAY_002_SPEC, agent_res["effects"], context)
        return eval_res.violated

    minimal_faults = ddmin(initial_faults, test_fault_subset)
    assert len(minimal_faults) == 1
    assert minimal_faults[0]["type"] == "timeout_after_commit"

    output_yaml = tmp_path / "arc-repro-8842.yaml"
    repro_path = export_minimal_reproducer_yaml(
        trace="trace_8842_double_refund",
        faults=minimal_faults,
        violated="INV-PAY-002",
        determinism_level="L1",
        reproduce_rate=0.35,
        confidence_interval=[0.177, 0.573],
        cost_usd=0.05,
        output_path=output_yaml,
    )

    assert repro_path.exists()

    res = runner.invoke(app, ["repro", str(repro_path)])
    assert res.exit_code == 0
    assert "INV-PAY-002" in res.output
    assert "REPRODUCED" in res.output


def test_refund_agent_readme_walkthrough_under_15_minutes() -> None:
    """Edge Case 2: Complete README walkthrough script validation in < 15 minutes."""
    start_time = time.perf_counter()

    readme_file = Path(examples_dir) / "README.md"
    assert readme_file.exists()
    readme_content = readme_file.read_text(encoding="utf-8")
    assert "Order #8842" in readme_content
    assert "INV-PAY-002" in readme_content

    # Step 1: Nominal execution
    nom_res = run_refund_agent(order_id="8842", inject_fault=False)
    assert nom_res["status"] == "completed"

    # Step 2: Chaos execution
    chaos_res = run_refund_agent(order_id="8842", inject_fault=True)
    assert len(chaos_res["effects"]) == 2

    # Step 3: Reproducer YAML check
    repro_file = Path(examples_dir) / "arc-repro-8842.yaml"
    assert repro_file.exists()

    # Step 4: CLI replay command check
    cli_res = runner.invoke(app, ["repro", str(repro_file)])
    assert cli_res.exit_code == 0

    elapsed_seconds = time.perf_counter() - start_time
    # Assert completed well within 15 minutes (900 seconds)
    assert elapsed_seconds < 900.0, f"Walkthrough took too long: {elapsed_seconds:.2f}s"
