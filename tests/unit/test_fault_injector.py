"""Unit tests for Fault Catalog Engine and Fault Injector (TASK-P2-001)."""

from __future__ import annotations

import os
import sys

# Ensure execution/fork-engine and execution/sandbox-runner are in sys.path
sys.path.insert(0, os.path.abspath("execution/fork-engine"))
sys.path.insert(0, os.path.abspath("execution/sandbox-runner"))

from fault_catalog import FaultCatalog, FaultSpec, FaultType
from injector import FaultInjector
from passive_ledger import PassiveEffectLedger


def test_inject_timeout_after_commit() -> None:
    """Happy Path 1: Injects timeout_after_commit at step 7 for issue_refund.

    Effect MUST be recorded in passive ledger, and response returned must be HTTP 504 Gateway Timeout.
    """
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=7,
            fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
            target_tool="issue_refund",
            params={"latency_ms": 10},
        )
    )

    injector = FaultInjector(catalog=catalog, ledger=ledger)
    args = {"order_id": "ORD-9988", "amount": 150.0}

    # Intercept tool call at step 7
    res = injector.intercept_tool_call(step_id=7, tool_name="issue_refund", args=args)

    # 1. Verify effect is recorded in passive effect ledger
    effects = ledger.get_effects()
    assert len(effects) == 1
    assert effects[0]["step_id"] == 7
    assert effects[0]["type"] == "issue_refund"
    assert effects[0]["delta"]["order_id"] == "ORD-9988"

    # 2. Verify returned client response is HTTP 504 Gateway Timeout
    assert res.get("status_code") == 504
    assert res.get("error") == "Gateway Timeout"
    assert "timeout_after_commit" in res.get("fault", "")


def test_inject_semantic_bad_schema_null_field() -> None:
    """Happy Path 2: Injects required_field_null for lookup_order tool response.

    Response returned MUST be {"order_id": None, "status": "active"}.
    """
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=3,
            fault_type=FaultType.REQUIRED_FIELD_NULL,
            target_tool="lookup_order",
            params={"field": "order_id"},
        )
    )

    injector = FaultInjector(catalog=catalog)
    args = {"order_id": "ORD-5544"}

    res = injector.intercept_tool_call(step_id=3, tool_name="lookup_order", args=args)

    assert res.get("order_id") is None
    assert res.get("status") == "active"


def test_inject_timeout_before_commit_does_not_record_effect() -> None:
    """Edge Case 1: Injects timeout_before_commit.

    Client receives timeout error AND effect ledger records ZERO resource changes.
    """
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=5,
            fault_type=FaultType.TIMEOUT_BEFORE_COMMIT,
            target_tool="issue_refund",
        )
    )

    injector = FaultInjector(catalog=catalog, ledger=ledger)
    args = {"order_id": "ORD-1122", "amount": 200.0}

    res = injector.intercept_tool_call(step_id=5, tool_name="issue_refund", args=args)

    # 1. Verify client received timeout
    assert res.get("status_code") == 504
    assert res.get("error") == "Gateway Timeout"

    # 2. Verify effect ledger did NOT record any effect
    effects = ledger.get_effects()
    assert len(effects) == 0


def test_fault_injection_at_wrong_step_is_ignored() -> None:
    """Edge Case 2: Fault spec specified for step 12, but run stops at step 6.

    Fault injector does not untimely trigger, and records fault_untriggered=True flag.
    """
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=12,
            fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
            target_tool="issue_refund",
        )
    )

    injector = FaultInjector(catalog=catalog, ledger=ledger)

    # Simulate steps 1 through 6
    for step in range(1, 7):
        res = injector.intercept_tool_call(
            step_id=step, tool_name="lookup_order", args={"order_id": f"ORD-{step}"}
        )
        assert res.get("status_code") != 504

    # 1. Verify fault was not triggered
    assert len(injector.get_applied_faults()) == 0

    # 2. Verify fault_untriggered flag is True
    assert injector.fault_untriggered is True
    assert injector.has_untriggered_faults() is True


def test_compound_faults_sequential() -> None:
    """Extra: Tests sequential compound fault chain across multiple steps."""
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog.from_list(
        [
            {
                "at_step": 1,
                "type": "http_500",
                "tool": "check_balance",
            },
            {
                "at_step": 2,
                "type": "timeout_after_commit",
                "tool": "issue_refund",
                "params": {"latency_ms": 5},
            },
        ]
    )

    injector = FaultInjector(catalog=catalog, ledger=ledger)

    # Step 1: http_500
    res1 = injector.intercept_tool_call(1, "check_balance", {"user_id": "U1"})
    assert res1.get("status_code") == 500

    # Step 2: timeout_after_commit
    res2 = injector.intercept_tool_call(2, "issue_refund", {"order_id": "ORD-1", "amount": 50})
    assert res2.get("status_code") == 504
    assert len(ledger.get_effects()) == 1

    # Verify all catalog faults were applied
    assert injector.fault_untriggered is False
    assert len(injector.get_applied_faults()) == 2
