"""Unit tests for Invariant Engine & Shadow Quarantine (TASK-P3-001)."""

from __future__ import annotations

import ast
import time
from typing import Any

import pytest

from arc.execution.invariant_engine.evaluator import (
    ALLOWED_CATEGORIES,
    AttrDict,
    DeterministicASTValidator,
    EvaluationResult,
    ForbiddenExpressionError,
    InvariantEvaluator,
    InvariantSpec,
    wrap_attr_dict,
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
        statement="Total financial.refund effects for an order must not exceed order total value",
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
    assert result.error is None


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
    assert result.error is None
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


def test_should_block_ci_rules() -> None:
    """Verifies all branches of should_block_ci for InvariantSpec and dict."""
    manager = QuarantineManager()

    res_violated = EvaluationResult(invariant_id="INV-1", violated=True)
    res_not_violated = EvaluationResult(invariant_id="INV-1", violated=False)

    # 1. Quarantined status (InvariantSpec & dict) never blocks CI even if violated
    inv_quarantined_spec = InvariantSpec(
        id="INV-1", statement="s", category="safety", status="quarantined", check="True"
    )
    assert manager.should_block_ci(inv_quarantined_spec, res_violated) is False
    assert manager.should_block_ci(inv_quarantined_spec, res_not_violated) is False

    inv_quarantined_dict = {"id": "INV-1", "status": "quarantined"}
    assert manager.should_block_ci(inv_quarantined_dict, res_violated) is False
    assert manager.should_block_ci(inv_quarantined_dict, res_not_violated) is False

    # 2. Deprecated status (InvariantSpec & dict) never blocks CI
    inv_deprecated_spec = InvariantSpec(
        id="INV-2", statement="s", category="safety", status="deprecated", check="True"
    )
    assert manager.should_block_ci(inv_deprecated_spec, res_violated) is False

    inv_deprecated_dict = {"id": "INV-2", "status": "deprecated"}
    assert manager.should_block_ci(inv_deprecated_dict, res_violated) is False

    # 3. Active status: blocks if violated, does not block if not violated
    inv_active_spec = InvariantSpec(
        id="INV-3", statement="s", category="safety", status="active", check="True"
    )
    assert manager.should_block_ci(inv_active_spec, res_violated) is True
    assert manager.should_block_ci(inv_active_spec, res_not_violated) is False

    inv_active_dict = {"id": "INV-3", "status": "active"}
    assert manager.should_block_ci(inv_active_dict, res_violated) is True
    assert manager.should_block_ci(inv_active_dict, res_not_violated) is False

    # 4. Dict without status defaults to "active"
    inv_default_dict = {"id": "INV-4"}
    assert manager.should_block_ci(inv_default_dict, res_violated) is True
    assert manager.should_block_ci(inv_default_dict, res_not_violated) is False


def test_auto_quarantine_check_dict_and_precision_calculation() -> None:
    """Verifies auto_quarantine_check with dict input and automatic precision calculation."""
    manager = QuarantineManager(min_triaged=10, precision_threshold=0.50)

    # Invariant dict with confirmed_real_bug and triaged, but no precision key
    inv_dict: dict[str, Any] = {
        "id": "INV-D1",
        "status": "active",
        "track_record": {
            "triaged": 10,
            "confirmed_real_bug": 3,  # precision = 3/10 = 0.30 (< 0.50)
        },
    }

    result = manager.auto_quarantine_check(inv_dict)

    assert result is True
    assert inv_dict["status"] == "quarantined"
    track_record: dict[str, Any] = inv_dict["track_record"]
    assert track_record["status"] == "quarantined"
    assert track_record["precision"] == 0.30
    downgrade_hist: list[dict[str, Any]] = inv_dict["downgrade_history"]
    assert len(downgrade_hist) == 1
    assert downgrade_hist[0]["from_status"] == "active"
    assert downgrade_hist[0]["to_status"] == "quarantined"
    assert downgrade_hist[0]["precision"] == 0.30
    assert downgrade_hist[0]["triaged"] == 10
    assert "Auto-quarantined: Precision 0.30" in downgrade_hist[0]["reason"]
    assert len(manager.downgrade_history) == 1
    assert manager.downgrade_history[0].precision == 0.30


def test_auto_quarantine_check_negative_cases() -> None:
    """Verifies conditions under which auto-quarantine does NOT trigger."""
    manager = QuarantineManager(min_triaged=10, precision_threshold=0.50)

    # 1. triaged < min_triaged
    inv_few_runs: dict[str, Any] = {
        "id": "INV-N1",
        "status": "active",
        "track_record": {"triaged": 9, "precision": 0.20},
    }
    assert manager.auto_quarantine_check(inv_few_runs) is False
    assert inv_few_runs["status"] == "active"

    # 2. precision >= precision_threshold
    inv_good_precision: dict[str, Any] = {
        "id": "INV-N2",
        "status": "active",
        "track_record": {"triaged": 15, "precision": 0.50},
    }
    assert manager.auto_quarantine_check(inv_good_precision) is False
    assert inv_good_precision["status"] == "active"

    # 3. status is not active (already quarantined)
    inv_already_quarantined: dict[str, Any] = {
        "id": "INV-N3",
        "status": "quarantined",
        "track_record": {"triaged": 15, "precision": 0.10},
    }
    assert manager.auto_quarantine_check(inv_already_quarantined) is False
    assert inv_already_quarantined["status"] == "quarantined"


def test_run_shadow_quarantine_full_lifecycle() -> None:
    """Verifies run_shadow_quarantine for both violated (bug) and passed (false positive) cases with dict & object."""
    evaluator = InvariantEvaluator()
    manager = QuarantineManager(min_triaged=10, precision_threshold=0.50)

    # 1. Dict invariant with violation (confirmed_real_bug increments)
    inv_dict: dict[str, Any] = {
        "id": "INV-SHADOW-1",
        "status": "active",
        "check": "len(effects) == 0",
        "track_record": {"triaged": 2, "confirmed_real_bug": 1, "precision": 0.5},
    }
    effects = [{"action": "write"}]  # len(effects) == 1 -> violated

    eval_result, block_ci = manager.run_shadow_quarantine(inv_dict, evaluator, effects)

    assert eval_result.violated is True
    track_record1: dict[str, Any] = inv_dict["track_record"]
    assert track_record1["triaged"] == 3
    assert track_record1["confirmed_real_bug"] == 2
    assert track_record1["precision"] == 2 / 3
    assert block_ci is True

    # 2. InvariantSpec with passed check (false positive increments, CI not blocked)
    inv_spec = InvariantSpec(
        id="INV-SHADOW-2",
        statement="Check pass",
        category="safety",
        status="active",
        check="len(effects) == 0",
        track_record={"triaged": 0},
    )

    eval_result2, block_ci2 = manager.run_shadow_quarantine(inv_spec, evaluator, [])

    assert eval_result2.violated is False
    assert inv_spec.track_record["triaged"] == 1
    assert inv_spec.track_record["false_positive"] == 1
    assert inv_spec.track_record["precision"] == 0.0
    assert block_ci2 is False

    # 3. Shadow run triggers auto-quarantine when crossing threshold
    inv_trigger: dict[str, Any] = {
        "id": "INV-SHADOW-3",
        "status": "active",
        "check": "len(effects) == 0",
        "track_record": {"triaged": 9, "confirmed_real_bug": 2, "precision": 2 / 9},
    }
    # Pass check -> false_positive becomes 8, confirmed stays 2, triaged becomes 10 -> precision = 2/10 = 0.20 (< 0.50)
    _, block_ci3 = manager.run_shadow_quarantine(inv_trigger, evaluator, [])

    track_trigger: dict[str, Any] = inv_trigger["track_record"]
    assert inv_trigger["status"] == "quarantined"
    assert track_trigger["triaged"] == 10
    assert track_trigger["precision"] == 0.20
    assert block_ci3 is False  # Because it was auto-quarantined, it must not block CI


def test_evaluator_syntax_and_runtime_error_handling() -> None:
    """Verifies evaluator gracefully handles evaluation errors and returns EvaluationResult with error."""
    evaluator = InvariantEvaluator()

    # Runtime division by zero
    inv_runtime_err = InvariantSpec(
        id="INV-ERR-001",
        statement="Divide by zero",
        category="consistency",
        check="1 / 0 == 0",
    )
    result = evaluator.evaluate(inv_runtime_err, [])
    assert result.violated is True, "Errors during evaluation fail-safe to violated=True"
    assert result.error is not None
    assert "division by zero" in result.error
    assert result.exec_time_ms >= 0


def test_attr_dict_and_wrap_attr_dict() -> None:
    """Verifies all branches of AttrDict and wrap_attr_dict."""
    # 1. AttrDict dot notation and nested dict
    ad = AttrDict({"a": {"b": 42}, "records": [{"val": 1}, 2], "prim": "hello"})
    assert ad.a.b == 42
    assert isinstance(ad.a, AttrDict)
    # Already AttrDict: doesn't re-wrap
    assert ad.a.b == 42

    # 2. List handling with dicts and non-dicts
    assert isinstance(ad.records, list)
    assert ad.records[0].val == 1
    assert isinstance(ad.records[0], AttrDict)
    assert ad.records[1] == 2

    # 3. Missing key raises AttributeError
    with pytest.raises(AttributeError) as exc_info:
        _ = ad.non_existent_key
    assert "has no attribute 'non_existent_key'" in str(exc_info.value)

    # 4. Setattr updates dict and attribute
    ad.new_prop = 999
    assert ad["new_prop"] == 999
    assert ad.new_prop == 999

    # 5. wrap_attr_dict with primitives and lists
    assert wrap_attr_dict(123) == 123
    assert wrap_attr_dict("str") == "str"
    assert wrap_attr_dict(None) is None
    wrapped_list = wrap_attr_dict([{"x": 10}, 20])
    assert isinstance(wrapped_list, list)
    assert wrapped_list[0].x == 10
    assert wrapped_list[1] == 20


def test_deterministic_ast_validator_comprehensive() -> None:
    """Verifies all branches of DeterministicASTValidator for calls, names, attributes, and imports."""
    evaluator = InvariantEvaluator()
    validator = DeterministicASTValidator()

    # 1. Imports forbidden (visit_Import and visit_ImportFrom)
    tree_import = ast.parse("import math")
    with pytest.raises(ForbiddenExpressionError) as exc1:
        validator.visit(tree_import)
    assert str(exc1.value) == "Imports are strictly forbidden in invariant expressions"

    tree_from_import = ast.parse("from math import sqrt")
    with pytest.raises(ForbiddenExpressionError) as exc2:
        validator.visit(tree_from_import)
    assert str(exc2.value) == "Imports are strictly forbidden in invariant expressions"

    # 1b. Method calls on objects: allowed vs forbidden
    _ = evaluator.compile("order.startswith('ORD')")
    _ = evaluator.compile("order.get('status') == 'pending'")
    _ = evaluator.compile("effects[0].get('id') == '1'")
    with pytest.raises(ForbiddenExpressionError) as exc_call:
        evaluator.compile("obj.random()")
    assert str(exc_call.value) == "Forbidden non-deterministic function call: 'random'"
    with pytest.raises(ForbiddenExpressionError) as exc_nested_call:
        evaluator.compile("effects[0].random()")
    assert str(exc_nested_call.value) == "Forbidden non-deterministic function call: 'random'"

    # 1c. Generator expression syntax fallback to mode="eval"
    parsed_gen = evaluator.compile("x for x in [1, 2]")
    assert isinstance(parsed_gen, ast.Expression)

    # 2. Dunder attribute access forbidden
    with pytest.raises(ForbiddenExpressionError) as exc3:
        evaluator.compile("order.__class__")
    assert "Forbidden dunder attribute access: '__class__'" in str(exc3.value)

    # 3. Attribute that is forbidden function
    with pytest.raises(ForbiddenExpressionError) as exc4:
        evaluator.compile("obj.open")
    assert "Forbidden non-deterministic attribute access: 'open'" in str(exc4.value)

    # 4. Name that is forbidden function
    with pytest.raises(ForbiddenExpressionError) as exc5:
        evaluator.compile("eval")
    assert "Forbidden identifier referenced: 'eval'" in str(exc5.value)

    # 5. Method call on object: time.sleep, math.random, etc.
    with pytest.raises(ForbiddenExpressionError) as exc6:
        evaluator.compile("time.ctime()")
    assert "Forbidden non-deterministic function call: 'time.ctime'" in str(exc6.value)

    # 6. Syntax error fallback to (expr) mode for multiline expressions
    multiline_expr = "1\n+ 2"
    parsed = evaluator.compile(multiline_expr)
    assert parsed is not None
    res_ml = evaluator.evaluate(InvariantSpec(id="INV-ML", statement="ml", category="safety", check=multiline_expr), [])
    assert res_ml.violated is False
    assert res_ml.error is None
    assert res_ml.details["result"] == 3

    # 7. Unparseable expression raises ForbiddenExpressionError
    with pytest.raises(ForbiddenExpressionError) as exc7:
        evaluator.compile(":::syntax_error:::")
    assert "Syntax error in expression" in str(exc7.value)


def test_evaluator_evaluate_full_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies evaluator dictionary conversion, context variable injection, and successful verdicts."""
    evaluator = InvariantEvaluator()

    # 1. Invariant passed as dict with all fields
    inv_dict_spec = {
        "id": "INV-DICT-FULL",
        "statement": "Dictionary spec evaluation",
        "category": "safety",
        "check": "context.tenant_id == 'T-01' and max_items == 5 and len(effects) == 1 and effects[0].action == 'create'",
        "severity": "high",
        "status": "active",
        "track_record": {"triaged": 0},
    }
    context = {"tenant_id": "T-01", "max_items": 5}
    effects = [{"action": "create"}]

    res = evaluator.evaluate(inv_dict_spec, effects, context)
    assert res.invariant_id == "INV-DICT-FULL"
    assert res.violated is False
    assert res.error is None
    assert res.details["result"] is True
    assert res.exec_time_ms >= 0

    # 2. Invariant violation (check returns False)
    inv_fail = InvariantSpec(
        id="INV-FAIL",
        statement="Fail check",
        category="budget",
        check="len(effects) == 99",
    )
    res_fail = evaluator.evaluate(inv_fail, effects, context)
    assert res_fail.violated is True
    assert res_fail.error is None
    assert res_fail.details["result"] is False

    # 3. Context is None
    inv_no_ctx = InvariantSpec(
        id="INV-NO-CTX",
        statement="No context",
        category="idempotence",
        check="len(effects) == 1",
    )
    res_no_ctx = evaluator.evaluate(inv_no_ctx, effects, context=None)
    assert res_no_ctx.violated is False
    assert res_no_ctx.error is None

    # 4. Context is non-dict
    res_str_ctx = evaluator.evaluate(inv_no_ctx, effects, context="string_context")
    assert res_str_ctx.violated is False
    assert res_str_ctx.error is None

    # 5. Order attribute handling when order is missing from context
    inv_order = InvariantSpec(
        id="INV-ORDER",
        statement="Order check",
        category="ordering",
        check="order is None",
    )
    res_order = evaluator.evaluate(inv_order, effects, context={"customer": "Bob"})
    assert res_order.violated is False
    assert res_order.error is None

    # 5b. Order attribute present in context and evaluate internals verification
    inv_order_test = InvariantSpec(
        id="INV-ORDER-TEST",
        statement="Order verification",
        category="ordering",
        check="order.amount == 100 and len(effects) == 1",
    )
    fake_time = 200.0

    def mock_perf_counter() -> float:
        nonlocal fake_time
        val = fake_time
        fake_time += 0.01  # 10 ms elapsed
        return val

    with monkeypatch.context() as m:
        m.setattr(time, "perf_counter", mock_perf_counter)
        res_order_test = evaluator.evaluate(
            inv_order_test, [{"id": "eff_1"}], context={"order": {"amount": 100}}
        )
        assert res_order_test.violated is False
        assert res_order_test.error is None
        assert res_order_test.exec_time_ms == pytest.approx(10.0)

    # 5c. Restricted builtins enforcement (sorted not in SAFE_BUILTINS)
    inv_sorted = InvariantSpec(
        id="INV-SAFE-BUILTIN",
        statement="Sorted builtin check",
        category="safety",
        check="sorted([1, 2]) == [1, 2]",
    )
    res_sorted = evaluator.evaluate(inv_sorted, [])
    assert res_sorted.violated is True
    assert res_sorted.error is not None
    assert "name 'sorted' is not defined" in res_sorted.error

    # 6. Runtime error during evaluation (undefined name)
    inv_undef = InvariantSpec(
        id="INV-UNDEF",
        statement="Undefined variable",
        category="consistency",
        check="missing_var > 10",
    )
    fake_time_err = 300.0

    def mock_perf_counter_err() -> float:
        nonlocal fake_time_err
        val = fake_time_err
        fake_time_err += 0.01  # 10 ms elapsed
        return val

    with monkeypatch.context() as m:
        m.setattr(time, "perf_counter", mock_perf_counter_err)
        res_undef = evaluator.evaluate(inv_undef, [])
        assert res_undef.invariant_id == "INV-UNDEF"
        assert res_undef.violated is True
        assert res_undef.error is not None
        assert "name 'missing_var' is not defined" in res_undef.error
        assert "[<invariant>]" in res_undef.error
        assert res_undef.exec_time_ms == pytest.approx(10.0)


def test_quarantine_manager_additional_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies edge cases in QuarantineManager (missing keys, custom thresholds, empty track_record)."""
    evaluator = InvariantEvaluator()
    manager = QuarantineManager(min_triaged=10, precision_threshold=0.50)

    # 1. auto_quarantine_check on dict without 'status' key (defaults to 'active')
    inv_no_status: dict[str, Any] = {
        "id": "INV-NO-STAT",
        "track_record": {"triaged": 10, "precision": 0.20},
    }
    assert manager.auto_quarantine_check(inv_no_status) is True
    assert inv_no_status["status"] == "quarantined"

    # 2. auto_quarantine_check on dict without 'track_record' key
    inv_no_track: dict[str, Any] = {
        "id": "INV-NO-TRACK",
        "status": "active",
    }
    assert manager.auto_quarantine_check(inv_no_track) is False

    # 3. auto_quarantine_check with custom threshold (e.g. 1.50) where default precision 1.0 < 1.50 triggers downgrade
    custom_mgr = QuarantineManager(min_triaged=10, precision_threshold=1.50)
    inv_default_prec: dict[str, Any] = {
        "id": "INV-DEF-PREC",
        "status": "active",
        "track_record": {"triaged": 12},  # No precision, no confirmed_real_bug -> precision defaults to 1.0 (< 1.50)
    }
    assert custom_mgr.auto_quarantine_check(inv_default_prec) is True
    assert inv_default_prec["status"] == "quarantined"

    # 4. run_shadow_quarantine with empty track_record and non-empty context
    inv_empty_track: dict[str, Any] = {
        "id": "INV-EMPTY-TRK",
        "status": "active",
        "check": "context.max_val == 50 and len(effects) == 1",
    }
    res, blocked = manager.run_shadow_quarantine(
        inv_empty_track, evaluator, [{"x": 1}], context={"max_val": 50}
    )
    assert res.violated is False
    assert res.error is None
    assert blocked is False
    # Verified track_record initialized and false_positive incremented
    trk: dict[str, Any] = inv_empty_track["track_record"]
    assert trk["triaged"] == 1
    assert trk["false_positive"] == 1
    assert trk["precision"] == 0.0

    # 5. run_shadow_quarantine with empty track_record and violation (confirmed_real_bug)
    inv_empty_track2: dict[str, Any] = {
        "id": "INV-EMPTY-TRK2",
        "status": "active",
        "check": "len(effects) == 99",
    }
    res2, blocked2 = manager.run_shadow_quarantine(inv_empty_track2, evaluator, [])
    assert res2.violated is True
    assert blocked2 is True
    trk2: dict[str, Any] = inv_empty_track2["track_record"]
    assert trk2["triaged"] == 1
    assert trk2["confirmed_real_bug"] == 1
    assert trk2["precision"] == 1.0

    # 6. InvariantSpec downgrade_history timestamp and record verification
    inv_spec = InvariantSpec(
        id="INV-SPEC-RECORD",
        statement="Spec record check",
        category="conservation",
        status="active",
        check="True",
        track_record={"triaged": 10, "precision": 0.10},
    )
    assert manager.auto_quarantine_check(inv_spec) is True
    assert inv_spec.status == "quarantined"
    assert inv_spec.track_record["status"] == "quarantined"
    assert len(inv_spec.downgrade_history) == 1
    rec = inv_spec.downgrade_history[0]
    assert isinstance(rec["timestamp"], float)
    assert rec["timestamp"] > 0
    assert rec["from_status"] == "active"
    assert rec["to_status"] == "quarantined"

    # 7. min_triaged=1 with missing 'triaged' key in track_record
    mgr_min1 = QuarantineManager(min_triaged=1, precision_threshold=0.50)
    inv_no_triaged_key: dict[str, Any] = {
        "id": "INV-NO-TRIAGED",
        "status": "active",
        "track_record": {"precision": 0.20},  # triaged missing, defaults to 0 (< 1)
    }
    assert mgr_min1.auto_quarantine_check(inv_no_triaged_key) is False

    # 8. triaged=0 with confirmed_real_bug and no precision: must not divide by zero
    inv_triaged_zero: dict[str, Any] = {
        "id": "INV-TRIAGED-ZERO",
        "status": "active",
        "track_record": {"triaged": 0, "confirmed_real_bug": 0},
    }
    assert manager.auto_quarantine_check(inv_triaged_zero) is False
    assert "precision" not in inv_triaged_zero["track_record"]

    # 9. run_shadow_quarantine with pre-existing false_positive count
    inv_fp_exist: dict[str, Any] = {
        "id": "INV-FP-EXIST",
        "status": "active",
        "check": "len(effects) == 0",
        "track_record": {"triaged": 5, "false_positive": 5, "confirmed_real_bug": 0},
    }
    manager.run_shadow_quarantine(inv_fp_exist, evaluator, [])
    assert inv_fp_exist["track_record"]["false_positive"] == 6

    # 10. Attributes with partial double underscores (__only_start or only_end__) are allowed
    evaluator.compile("obj.__start_only")
    evaluator.compile("obj.end_only__")

    # 11. Mock compile error to test compilation error branch
    class BadAST(ast.AST):
        pass

    inv_compile_err = InvariantSpec(
        id="INV-COMP-ERR", statement="s", category="safety", check="True"
    )
    orig_compile = evaluator.compile
    evaluator.compile = lambda check_expression: BadAST()  # type: ignore[assignment]
    fake_time = 50.0

    def mock_perf_counter() -> float:
        nonlocal fake_time
        val = fake_time
        fake_time += 0.01  # 10 ms elapsed
        return val

    monkeypatch.setattr(time, "perf_counter", mock_perf_counter)
    try:
        res_comp_err = evaluator.evaluate(inv_compile_err, [])
        assert res_comp_err.invariant_id == "INV-COMP-ERR"
        assert res_comp_err.violated is True
        assert res_comp_err.error is not None
        assert "Compilation error" in res_comp_err.error
        assert res_comp_err.exec_time_ms == pytest.approx(10.0)
    finally:
        evaluator.compile = orig_compile

    # 12. auto_quarantine_check with triaged == 1 and confirmed_real_bug == 0
    inv_t1: dict[str, Any] = {
        "id": "INV-T1",
        "status": "active",
        "track_record": {"triaged": 1, "confirmed_real_bug": 0},
    }
    assert mgr_min1.auto_quarantine_check(inv_t1) is True
    assert inv_t1["status"] == "quarantined"
    assert inv_t1["track_record"]["precision"] == 0.0



