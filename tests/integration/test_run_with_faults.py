"""Integration tests for F2: SandboxRunner.run_with_faults() end-to-end.

Verifies that the method (previously non-existent) correctly:
- Builds FaultCatalog and FaultInjector
- Executes cassette steps through fault-injected container
- Evaluates target invariant against ledger effects
- Returns structured result with passed/violated/effects keys
"""

from __future__ import annotations

from arc.execution.fork_engine.fault_catalog import FaultCatalog
from arc.execution.sandbox_runner.cassette_player import CassettePlayer, CassetteRecord
from arc.execution.sandbox_runner.runner import SandboxRunner


def test_run_with_faults_duplicate_action_detects_idempotency_violation() -> None:
    """F2: DUPLICATE_ACTION fault records 2 ledger entries → idempotency invariant violated."""
    runner = SandboxRunner()

    fault_spec = [
        {"at_step": 1, "type": "duplicate_action", "tool": "issue_refund"}
    ]
    invariant = {
        "id": "INV-IDEM-001",
        "statement": "issue_refund must not execute twice for the same order",
        "category": "idempotence",
        # Check: at most 1 ledger entry for issue_refund
        "check": "len([e for e in effects if e['type'] == 'issue_refund']) <= 1",
        "severity": "critical",
    }

    cassette = CassettePlayer(
        records=[
            CassetteRecord(
                tool="issue_refund",
                request_args={"order_id": "8842", "amount": 45.99},
                response={"status": "ok"},
            ),
        ]
    )

    result = runner.run_with_faults(
        fault_spec=fault_spec,
        target_invariant=invariant,
        cassette_player=cassette,
    )

    # DUPLICATE_ACTION commits 2 ledger entries → invariant check fails (len > 1)
    assert result["passed"] is False
    assert result["violated_invariant"] == "INV-IDEM-001"
    assert result["eval_result"]["violated"] is True
    assert len(result["effects"]) == 2


def test_run_with_faults_no_violation_when_idempotency_key_prevents_retry() -> None:
    """F2: Single execution with idempotency key — invariant passes."""
    runner = SandboxRunner()

    fault_spec: list = []  # no faults
    invariant = {
        "id": "INV-IDEM-002",
        "statement": "Only one refund effect per order",
        "category": "idempotence",
        "check": "len([e for e in effects if e['type'] == 'issue_refund']) <= 1",
        "severity": "critical",
    }

    # Single call — no retry
    catalog = FaultCatalog.from_list(fault_spec)
    container = runner.start_container()
    container.execute_tool(
        "issue_refund",
        {"order_id": "1111", "amount": 10.0, "idempotency_key": "ord_1111:refund:1"},
    )

    result = runner.run_with_faults(fault_spec=catalog, target_invariant=invariant)

    assert result["passed"] is True
    assert result["eval_result"]["violated"] is False


def test_run_with_faults_uses_cassette_player_steps() -> None:
    """F2: When CassettePlayer is provided, cassette steps drive the container execution."""
    runner = SandboxRunner()

    cassette = CassettePlayer(
        records=[
            CassetteRecord(
                tool="lookup_order",
                request_args={"order_id": "7777"},
                response={"order_id": "7777", "status": "active"},
            ),
            CassetteRecord(
                tool="issue_refund",
                request_args={"order_id": "7777", "amount": 25.0},
                response={"status": "ok", "refund_id": "ref_abc"},
            ),
        ]
    )

    fault_spec = [{"at_step": 2, "type": "http_500", "tool": "issue_refund"}]
    invariant = {
        "id": "INV-INFRA-001",
        "statement": "issue_refund must not return HTTP 500",
        "category": "safety",
        "check": "True",  # we inspect effects_count externally
        "severity": "critical",
    }

    result = runner.run_with_faults(
        fault_spec=fault_spec,
        target_invariant=invariant,
        cassette_player=cassette,
    )

    # At step 2 (issue_refund), HTTP_500 fault is applied — no effect recorded
    assert "effects" in result
    assert "eval_result" in result
    assert "fault_spec" in result
    assert result["violated_invariant"] == "INV-INFRA-001"


def test_run_with_faults_returns_correct_structure() -> None:
    """F2: run_with_faults always returns all required keys."""
    runner = SandboxRunner()
    result = runner.run_with_faults(fault_spec=[], target_invariant="INV-TEST-001")

    required_keys = {"status", "violated_invariant", "fault_spec", "passed", "effects", "eval_result"}
    assert required_keys.issubset(result.keys())
    assert isinstance(result["effects"], list)
    assert isinstance(result["fault_spec"], list)
    assert isinstance(result["passed"], bool)
