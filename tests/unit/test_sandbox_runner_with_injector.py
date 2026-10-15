"""Tests for F1: FaultInjector wired into SandboxContainer.execute_tool().

Verifies that fault specs are actually applied during sandbox replay,
not bypassed as they were before the F1 fix.
"""

from __future__ import annotations

from arc.execution.fork_engine.fault_catalog import FaultCatalog, FaultSpec, FaultType
from arc.execution.fork_engine.injector import FaultInjector
from arc.execution.sandbox_runner.passive_ledger import PassiveEffectLedger
from arc.execution.sandbox_runner.runner import ReplayMode, SandboxRunner


def test_execute_tool_routes_through_injector_http500() -> None:
    """F1: FaultInjector HTTP_500 spec is applied when execute_tool is called."""
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(at_step=1, fault_type=FaultType.HTTP_500, target_tool="issue_refund")
    )
    injector = FaultInjector(catalog=catalog, ledger=ledger)

    runner = SandboxRunner(ledger=ledger)
    container = runner.start_container(injector=injector)

    res = container.execute_tool("issue_refund", {"order_id": "1234", "amount": 50.0})

    assert res.get("status_code") == 500
    assert len(injector.get_applied_faults()) == 1


def test_execute_tool_routes_through_injector_timeout_after_commit() -> None:
    """F1: TIMEOUT_AFTER_COMMIT records ledger entry AND returns 504."""
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=1,
            fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
            target_tool="issue_refund",
        )
    )
    injector = FaultInjector(catalog=catalog, ledger=ledger)

    runner = SandboxRunner(ledger=ledger)
    container = runner.start_container(injector=injector)

    res = container.execute_tool("issue_refund", {"order_id": "8842", "amount": 45.99})

    # Fault applied
    assert res.get("status_code") == 504
    assert res.get("error") == "Gateway Timeout"

    # Effect IS recorded in ledger (after-commit)
    effects = ledger.get_effects()
    assert len(effects) == 1
    assert effects[0]["type"] == "issue_refund"


def test_execute_tool_step_counter_increments() -> None:
    """F1: Step counter increments correctly across multiple execute_tool calls."""
    runner = SandboxRunner()
    container = runner.start_container()

    container.execute_tool("lookup_order", {"order_id": "001"})
    container.execute_tool("lookup_order", {"order_id": "002"})
    container.execute_tool("issue_refund", {"order_id": "003", "amount": 10.0})

    assert container._step_counter == 3


def test_passive_mode_bypasses_injector() -> None:
    """F7: PASSIVE replay mode traps mutating calls without fault injection."""
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(at_step=1, fault_type=FaultType.HTTP_500, target_tool="issue_refund")
    )
    injector = FaultInjector(catalog=catalog, ledger=ledger)

    runner = SandboxRunner(ledger=ledger)
    container = runner.start_container(
        injector=injector,
        replay_mode=ReplayMode.PASSIVE,
    )

    res = container.execute_tool("issue_refund", {"order_id": "9999", "amount": 20.0})

    # In PASSIVE mode, no fault injection — normal trap response
    assert res.get("status_code") != 500
    assert res.get("recorded") is True
    # Fault not applied
    assert len(injector.get_applied_faults()) == 0
