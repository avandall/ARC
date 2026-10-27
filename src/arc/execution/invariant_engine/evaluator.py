"""CEL & Restricted AST Python Deterministic Invariant Evaluator (TASK-P3-001).

Evaluates invariant check statements on Effect Ledger and Context deterministically,
strictly prohibiting non-deterministic functions (e.g., random(), time.now()) and I/O.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from typing import Any

ALLOWED_CATEGORIES: set[str] = {
    "safety",
    "conservation",
    "idempotence",
    "ordering",
    "authority",
    "budget",
    "consistency",
}

FORBIDDEN_FUNCTIONS: set[str] = {
    "random",
    "randint",
    "randrange",
    "choice",
    "uniform",
    "seed",
    "now",
    "time",
    "ctime",
    "localtime",
    "gmtime",
    "mktime",
    "strftime",
    "strptime",
    "today",
    "timestamp",
    "uuid",
    "uuid1",
    "uuid3",
    "uuid4",
    "uuid5",
    "open",
    "read",
    "write",
    "exec",
    "eval",
    "compile",
    "__import__",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "input",
    "print",
}

SAFE_BUILTINS: dict[str, Any] = {
    "sum": sum,
    "len": len,
    "max": max,
    "min": min,
    "abs": abs,
    "all": all,
    "any": any,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "filter": filter,
    "map": map,
    "range": range,
    "True": True,
    "False": False,
    "None": None,
}


class ForbiddenExpressionError(ValueError):
    """Raised when an invariant expression contains forbidden non-deterministic calls or I/O."""


class AttrDict(dict):
    """Dict wrapper supporting dot-notation attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            val = self[name]
            if isinstance(val, dict) and not isinstance(val, AttrDict):
                return AttrDict(val)
            elif isinstance(val, list):
                return [
                    AttrDict(x) if isinstance(x, dict) and not isinstance(x, AttrDict) else x
                    for x in val
                ]
            return val
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def wrap_attr_dict(obj: Any) -> Any:
    """Recursively wrap dicts into AttrDict for attribute dot notation support."""
    if isinstance(obj, dict) and not isinstance(obj, AttrDict):
        return AttrDict({k: wrap_attr_dict(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [wrap_attr_dict(item) for item in obj]
    return obj


@dataclass
class InvariantSpec:
    """Specification of an Invariant rule."""

    id: str
    statement: str
    category: str
    check: str
    severity: str = "critical"
    source: list[str] = field(default_factory=list)
    approved_by: str = ""
    applies_when: str | None = None
    evaluator: str = "expression"
    status: str = "active"  # active | quarantined | deprecated
    downgrade_history: list[dict[str, Any]] = field(default_factory=list)
    track_record: dict[str, Any] = field(
        default_factory=lambda: {
            "triaged": 0,
            "confirmed_real_bug": 0,
            "false_positive": 0,
            "precision": 1.0,
            "status": "active",
        }
    )

    def __post_init__(self) -> None:
        if self.category not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"Invalid invariant category '{self.category}'. Must be one of {ALLOWED_CATEGORIES}"
            )


@dataclass
class EvaluationResult:
    """Result of evaluating an Invariant."""

    invariant_id: str
    violated: bool
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    exec_time_ms: float = 0.0


class DeterministicASTValidator(ast.NodeVisitor):
    """AST visitor enforcing deterministic execution rules on invariant expressions."""

    def visit_Call(self, node: ast.Call) -> None:
        """Inspects function call node and raises ForbiddenExpressionError if non-deterministic."""
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_FUNCTIONS:
                raise ForbiddenExpressionError(
                    f"Forbidden non-deterministic function call: '{node.func.id}'"
                )
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                full_call = f"{node.func.value.id}.{node.func.attr}"
                if full_call in FORBIDDEN_FUNCTIONS or node.func.value.id in FORBIDDEN_FUNCTIONS:
                    raise ForbiddenExpressionError(
                        f"Forbidden non-deterministic function call: '{full_call}'"
                    )
            if node.func.attr in FORBIDDEN_FUNCTIONS:
                raise ForbiddenExpressionError(
                    f"Forbidden non-deterministic function call: '{node.func.attr}'"
                )

        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Inspects identifier name and raises ForbiddenExpressionError if forbidden."""
        if node.id in FORBIDDEN_FUNCTIONS:
            raise ForbiddenExpressionError(
                f"Forbidden identifier referenced: '{node.id}'"
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Inspects attribute access and forbids dunder attributes or forbidden functions."""
        if node.attr.startswith("__") and node.attr.endswith("__"):
            raise ForbiddenExpressionError(
                f"Forbidden dunder attribute access: '{node.attr}'"
            )
        if node.attr in FORBIDDEN_FUNCTIONS:
            raise ForbiddenExpressionError(
                f"Forbidden non-deterministic attribute access: '{node.attr}'"
            )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Inspects import statement and unconditionally forbids imports in invariant checks."""
        raise ForbiddenExpressionError("Imports are strictly forbidden in invariant expressions")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Inspects from-import statement and unconditionally forbids imports in invariant checks."""
        raise ForbiddenExpressionError("Imports are strictly forbidden in invariant expressions")


class InvariantEvaluator:
    """Deterministic Invariant Evaluator using restricted AST parsing."""

    def compile(self, check_expression: str) -> ast.AST:
        """Parses and validates check expression for deterministic safety."""
        expr = check_expression.strip()
        try:
            parsed = ast.parse(expr, mode="eval")
        except SyntaxError:
            try:
                parsed = ast.parse(f"({expr})", mode="eval")
            except SyntaxError as e:
                raise ForbiddenExpressionError(f"Syntax error in expression: {e}") from e

        validator = DeterministicASTValidator()
        validator.visit(parsed)
        return parsed

    def evaluate(
        self,
        invariant: InvariantSpec | dict[str, Any],
        effects: list[dict[str, Any] | Any],
        context: dict[str, Any] | Any | None = None,
    ) -> EvaluationResult:
        """Evaluates invariant against effect ledger and context deterministically."""
        start_time = time.perf_counter()

        if isinstance(invariant, dict):
            inv_id: str = invariant["id"]
            check_expr: str = invariant["check"]
        else:
            inv_id = invariant.id
            check_expr = invariant.check

        try:
            compiled_ast = self.compile(check_expr)
            code_obj = compile(compiled_ast, "<invariant>", "eval")  # type: ignore[call-overload]
        except ForbiddenExpressionError:
            raise
        except Exception as exc:  # noqa: BLE001
            return EvaluationResult(
                invariant_id=inv_id,
                violated=True,
                error=f"Compilation error: {exc}",
                exec_time_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        wrapped_effects = [wrap_attr_dict(e) for e in effects]
        wrapped_context = wrap_attr_dict(context or {})

        eval_locals: dict[str, Any] = {
            "effects": wrapped_effects,
            "context": wrapped_context,
            "order": getattr(wrapped_context, "order", None),
        }

        if isinstance(wrapped_context, dict):
            for k, v in wrapped_context.items():
                if k not in eval_locals:
                    eval_locals[k] = v

        eval_globals: dict[str, Any] = {"__builtins__": SAFE_BUILTINS, **eval_locals}

        try:
            _eval_fn = __import__("builtins").eval
            result = _eval_fn(code_obj, eval_globals)
            violated = not bool(result)
            exec_time = (time.perf_counter() - start_time) * 1000.0
            return EvaluationResult(
                invariant_id=inv_id,
                violated=violated,
                details={"result": result},
                exec_time_ms=exec_time,
            )
        except Exception as exc:  # noqa: BLE001
            exec_time = (time.perf_counter() - start_time) * 1000.0
            return EvaluationResult(
                invariant_id=inv_id,
                violated=True,
                error=f"Runtime error during evaluation: {exc} [{code_obj.co_filename}]",
                exec_time_ms=exec_time,
            )
