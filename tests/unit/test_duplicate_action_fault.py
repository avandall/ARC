"""Tests for F8: Group C concurrency & idempotency fault types.

DUPLICATE_ACTION, PARTIAL_SUCCESS, CONCURRENT_WRITE.
"""

from __future__ import annotations

from arc.execution.fork_engine.fault_catalog import (
    CONCURRENCY_FAULTS,
    FaultCatalog,
    FaultSpec,
    FaultType,
)
from arc.execution.fork_engine.injector import FaultInjector
from arc.execution.sandbox_runner.passive_ledger import PassiveEffectLedger
from arc.execution.tool_models.refund_domain.mock_payment import (
    SUPPORTED_FAULTS,
    MockPaymentGateway,
)

# ── FaultType enum ─────────────────────────────────────────────────────────────

def test_group_c_fault_types_exist() -> None:
    """F8: All Group C fault types are defined in FaultType enum."""
    assert FaultType.DUPLICATE_ACTION.value == "duplicate_action"
    assert FaultType.PARTIAL_SUCCESS.value == "partial_success"
    assert FaultType.CONCURRENT_WRITE.value == "concurrent_write"


def test_concurrency_faults_set_contains_all_group_c() -> None:
    """F8: CONCURRENCY_FAULTS set contains all three new fault types."""
    assert "duplicate_action" in CONCURRENCY_FAULTS
    assert "partial_success" in CONCURRENCY_FAULTS
    assert "concurrent_write" in CONCURRENCY_FAULTS


# ── FaultInjector handlers ─────────────────────────────────────────────────────

def test_duplicate_action_records_two_ledger_entries() -> None:
    """F8: DUPLICATE_ACTION commits 2 effects to ledger and returns HTTP 200."""
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=1,
            fault_type=FaultType.DUPLICATE_ACTION,
            target_tool="issue_refund",
        )
    )
    injector = FaultInjector(catalog=catalog, ledger=ledger)

    res = injector.intercept_tool_call(
        step_id=1, tool_name="issue_refund", args={"order_id": "8842", "amount": 50.0}
    )

    assert res.get("status_code") == 200
    assert res.get("fault") == "duplicate_action"
    effects = ledger.get_effects()
    assert len(effects) == 2, "DUPLICATE_ACTION must produce exactly 2 ledger entries"
    assert all(e["type"] == "issue_refund" for e in effects)


def test_partial_success_records_one_entry_then_returns_500() -> None:
    """F8: PARTIAL_SUCCESS commits 1 effect (Write A ok) then returns HTTP 500 (Write B fail)."""
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=3,
            fault_type=FaultType.PARTIAL_SUCCESS,
            target_tool="issue_refund",
        )
    )
    injector = FaultInjector(catalog=catalog, ledger=ledger)

    res = injector.intercept_tool_call(
        step_id=3, tool_name="issue_refund", args={"order_id": "1234", "amount": 25.0}
    )

    assert res.get("status_code") == 500
    assert res.get("partial_commit") is True
    effects = ledger.get_effects()
    assert len(effects) == 1, "PARTIAL_SUCCESS must commit exactly 1 effect (Write A)"


def test_concurrent_write_returns_409_and_no_ledger_entry() -> None:
    """F8: CONCURRENT_WRITE returns 409 Conflict without committing any ledger effect."""
    ledger = PassiveEffectLedger()
    catalog = FaultCatalog()
    catalog.add_fault(
        FaultSpec(
            at_step=2,
            fault_type=FaultType.CONCURRENT_WRITE,
            target_tool="issue_refund",
        )
    )
    injector = FaultInjector(catalog=catalog, ledger=ledger)

    res = injector.intercept_tool_call(
        step_id=2, tool_name="issue_refund", args={"order_id": "5555", "amount": 99.0}
    )

    assert res.get("status_code") == 409
    assert "conflict" in res.get("error", "").lower()
    assert res.get("conflict_resource") == "5555"
    effects = ledger.get_effects()
    assert len(effects) == 0, "CONCURRENT_WRITE must not commit any effect"


# ── MockPaymentGateway SUPPORTED_FAULTS ───────────────────────────────────────

def test_mock_payment_gateway_accepts_group_c_faults() -> None:
    """F8: MockPaymentGateway does not raise UnsupportedFaultException for Group C types."""
    gateway = MockPaymentGateway(balances={"order:0001": 200.0})

    for fault_type in ("duplicate_action", "partial_success", "concurrent_write"):
        res = gateway.handle(
            {"order_id": "0001", "amount": 10.0},
            injected_fault={"type": fault_type},
        )
        assert res.get("status") == "ok"


def test_group_c_in_supported_faults_set() -> None:
    """F8: All Group C types appear in SUPPORTED_FAULTS set."""
    assert "duplicate_action" in SUPPORTED_FAULTS
    assert "partial_success" in SUPPORTED_FAULTS
    assert "concurrent_write" in SUPPORTED_FAULTS
