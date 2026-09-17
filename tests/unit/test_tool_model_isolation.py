"""Unit tests for Tool Model Plugin Architecture & State Isolation (TASK-P2-002)."""

from __future__ import annotations

import os
import sys

import pytest

# Ensure execution/tool-models and refund_domain are in sys.path
sys.path.insert(0, os.path.abspath("execution/tool-models"))
sys.path.insert(0, os.path.abspath("execution/tool-models/refund_domain"))

from base import UnsupportedFaultException, registry
from mock_payment import MockPaymentGateway


def test_mock_payment_gateway_idempotency_handling() -> None:
    """Happy Path 1: Calling handle twice with identical idempotency key.

    First call executes refund and deducts balance.
    Second call detects processed key, returns cached response, and does not deduct balance again.
    """
    gateway = MockPaymentGateway(balances={"order:8842": 100.0})
    request = {
        "order_id": "8842",
        "amount": 45.99,
        "idempotency_key": "ord_8842:refund:1",
    }

    # First call
    response1 = gateway.handle(request)
    assert response1["status"] == "ok"
    assert response1["remaining_balance"] == pytest.approx(54.01)
    assert len(gateway.effects) == 1

    # Second call (same idempotency key)
    response2 = gateway.handle(request)
    assert response2 == response1
    assert gateway.balances["order:8842"] == pytest.approx(54.01)
    assert len(gateway.effects) == 1


def test_tool_model_to_effect_ledger_entries() -> None:
    """Happy Path 2: Verifies effect ledger entries conform to schema §4.3.

    Checks financial.refund type, order:8842 resource, and negative delta.
    """
    gateway = MockPaymentGateway(balances={"order:8842": 100.0})
    request = {
        "order_id": "8842",
        "amount": 45.99,
        "idempotency_key": "ord_8842:refund:1",
    }
    gateway.handle(request)

    effects = gateway.to_effect_ledger_entries()
    assert len(effects) == 1
    effect = effects[0]

    assert effect["type"] == "financial.refund"
    assert effect["resource"] == "order:8842"
    assert effect["idempotency_key"] == "ord_8842:refund:1"
    assert effect["delta"]["amount"] == -45.99
    assert effect["delta"]["amount_cents"] == -4599
    assert effect["reversible"] is False


def test_k_runs_state_isolation_regression() -> None:
    """Edge Case 1: Verifies state isolation between parallel K-run branches.

    Branch A balance mutation must not spill over or alter Branch B balance.
    """
    base_gateway = MockPaymentGateway(balances={"order:8842": 100.0})
    branch_a = base_gateway.clone_fresh_state("seed_snapshot_001")
    branch_b = base_gateway.clone_fresh_state("seed_snapshot_001")

    assert isinstance(branch_a, MockPaymentGateway)
    assert isinstance(branch_b, MockPaymentGateway)

    # Issue refund on Branch A only
    branch_a.handle(
        {
            "order_id": "8842",
            "amount": 45.99,
            "idempotency_key": "ord_8842:refund:1",
        }
    )

    # Check Branch A state mutated
    assert branch_a.balances["order:8842"] == pytest.approx(54.01)
    assert len(branch_a.to_effect_ledger_entries()) == 1

    # Check Branch B and base_gateway remain pristine at 100.0
    assert branch_b.balances["order:8842"] == 100.0
    assert len(branch_b.to_effect_ledger_entries()) == 0
    assert base_gateway.balances["order:8842"] == 100.0


def test_tool_model_rejects_unsupported_fault_type() -> None:
    """Edge Case 2: Unknown fault type 'nuclear_meltdown' raises UnsupportedFaultException."""
    gateway = MockPaymentGateway()
    fault_spec = {"type": "nuclear_meltdown"}

    with pytest.raises(UnsupportedFaultException) as exc_info:
        gateway.handle({"order_id": "8842", "amount": 10.0}, injected_fault=fault_spec)

    assert "nuclear_meltdown" in str(exc_info.value)
    assert "MockPaymentGateway" in str(exc_info.value)


def test_tool_model_registry_registration() -> None:
    """Verifies that MockPaymentGateway is properly registered in global registry."""
    assert "issue_refund" in registry
    assert registry["issue_refund"] == MockPaymentGateway
