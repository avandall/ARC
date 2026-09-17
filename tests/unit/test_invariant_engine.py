"""Unit tests for Invariant Engine & Shadow Quarantine (TASK-P3-001)."""

from __future__ import annotations

import pytest

from arc.execution.invariant_engine.evaluator import (
    ALLOWED_CATEGORIES,
    EvaluationResult,
    ForbiddenExpressionError,
    InvariantEvaluator,
    InvariantSpec,
)
from arc.execution.invariant_engine.quarantine import QuarantineManager


def test_cel_evaluator_conservation_rule() -> None:
    """Happy Path 1: Evaluates invariant INV-PAY-002 (total refund <= order total).

    Effect Ledger contains 2 refund effects totaling $91.98 for order of $45.99.
    Result: Evaluator returns violated=True.
    """
    evaluator = InvariantEvaluator()

    invariant = InvariantSpec(
        id="INV-PAY-002",
        statement="Tổng các effect financial.refund cho một order không vượt quá giá trị order",
        category="conservation",
        severity="critical",
        check="""
sum(e.delta.amount_cents for e in effects
    if e.type == "financial.refund" and e.resource == order.ref)
<= order.total_cents
""",
    )

    context = {
        "order": {
            "ref": "ORD-8842",
            "total_cents": 4599,  # $45.99
        }
    }

    effects = [
        {
            "type": "financial.refund",
            "resource": "ORD-8842",
            "delta": {"amount_cents": 4599},  # $45.99
        },
        {
            "type": "financial.refund",
            "resource": "ORD-8842",
            "delta": {"amount_cents": 4599},  # $45.99 -> Total refund = $91.98 (9198 cents)
        },
    ]

    result: EvaluationResult = evaluator.evaluate(invariant, effects, context)

    assert result.invariant_id == "INV-PAY-002"
    assert result.violated is True, "Expected invariant INV-PAY-002 to be violated because $91.98 > $45.99"


def test_shadow_mode_quarantine_execution() -> None:
    """Happy Path 2: Invariant in 'quarantined' state is evaluated in shadow mode.

    Evaluator computes the result and updates track_record.triaged,
    but should_block_ci() returns False.
    """
    evaluator = InvariantEvaluator()
    manager = QuarantineManager()

    invariant = InvariantSpec(
        id="INV-PAY-002",
        statement="Total refund <= order total",
        category="conservation",
        status="quarantined",
        check="sum(e.delta.amount_cents for e in effects) <= order.total_cents",
        track_record={
            "triaged": 5,
            "confirmed_real_bug": 2,
            "false_positive": 3,
            "precision": 0.40,
            "status": "quarantined",
        },
    )

    context = {"order": {"total_cents": 1000}}
    effects = [{"delta": {"amount_cents": 2000}}]  # Violated

    result, block_ci = manager.run_shadow_quarantine(invariant, evaluator, effects, context)

    assert result.violated is True
    assert invariant.track_record["triaged"] == 6, "Expected triaged count to increment to 6"
    assert block_ci is False, "Quarantined invariant MUST NOT block CI (should_block_ci returns False)"


def test_evaluator_blocks_non_deterministic_functions() -> None:
    """Edge Case 1: Invariant check expression containing random() or time.now().

    Evaluator refuses to compile/evaluate expression and raises ForbiddenExpressionError.
    """
    evaluator = InvariantEvaluator()

    expr_random = "random() > 0.5"
    with pytest.raises(ForbiddenExpressionError) as exc_info1:
        evaluator.compile(expr_random)
    assert "Forbidden" in str(exc_info1.value)

    expr_time = "time.now() > 100"
    with pytest.raises(ForbiddenExpressionError) as exc_info2:
        evaluator.compile(expr_time)
    assert "Forbidden" in str(exc_info2.value)

    # Also test evaluation call
    inv_bad = InvariantSpec(
        id="INV-BAD-001",
        statement="Non-deterministic expression test",
        category="safety",
        check="time.now() > 0",
    )
    with pytest.raises(ForbiddenExpressionError):
        evaluator.evaluate(inv_bad, [])


def test_auto_quarantine_on_low_precision() -> None:
    """Edge Case 2: Invariant precision drops to 0.40 after 12 triaged runs.

    Auto-quarantine check transitions invariant status from 'active' to 'quarantined'
    and records downgrade history.
    """
    manager = QuarantineManager(min_triaged=10, precision_threshold=0.50)

    invariant = InvariantSpec(
        id="INV-PAY-003",
        statement="Idempotency refund check",
        category="idempotence",
        status="active",
        check="len(effects) <= 1",
        track_record={
            "triaged": 12,
            "confirmed_real_bug": 4,
            "false_positive": 8,
            "precision": 0.40,
            "status": "active",
        },
    )

    quarantined = manager.auto_quarantine_check(invariant)

    assert quarantined is True
    assert invariant.status == "quarantined"
    assert len(manager.downgrade_history) == 1
    record = manager.downgrade_history[0]
    assert record.from_status == "active"
    assert record.to_status == "quarantined"
    assert record.precision == 0.40
    assert record.triaged == 12


def test_invariant_categories_validation() -> None:
    """Tests supported 7 invariant categories and invalid category rejection."""
    for category in ALLOWED_CATEGORIES:
        inv = InvariantSpec(
            id=f"INV-TEST-{category}",
            statement=f"Test statement for {category}",
            category=category,
            check="True",
        )
        assert inv.category == category

    with pytest.raises(ValueError) as exc_info:
        InvariantSpec(
            id="INV-INVALID",
            statement="Invalid category test",
            category="unsupported_category",
            check="True",
        )
    assert "Invalid invariant category" in str(exc_info.value)
