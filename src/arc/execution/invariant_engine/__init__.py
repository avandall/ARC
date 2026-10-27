"""ARC Invariant Engine.

Provides deterministic invariant evaluation using restricted AST parsing (CEL-like)
and automated quarantine lifecycle management for noisy or flaky rules.

Classes:
    InvariantEvaluator: Deterministically evaluates check expressions on effect ledgers.
    InvariantSpec: Dataclass specifying invariant metadata, category, and check expressions.
    EvaluationResult: Dataclass holding verdict, execution time, and error details.
    DeterministicASTValidator: AST NodeVisitor forbidding non-deterministic calls and I/O.
    ForbiddenExpressionError: Exception raised when check expression contains forbidden calls.
    QuarantineManager: Manages auto-quarantine downgrades and shadow mode execution.
    DowngradeRecord: Record of invariant status downgrade events.
"""

from __future__ import annotations

from arc.execution.invariant_engine.evaluator import (
    ALLOWED_CATEGORIES,
    FORBIDDEN_FUNCTIONS,
    SAFE_BUILTINS,
    AttrDict,
    DeterministicASTValidator,
    EvaluationResult,
    ForbiddenExpressionError,
    InvariantEvaluator,
    InvariantSpec,
    wrap_attr_dict,
)
from arc.execution.invariant_engine.quarantine import (
    DowngradeRecord,
    QuarantineManager,
)

__all__ = [
    "ALLOWED_CATEGORIES",
    "FORBIDDEN_FUNCTIONS",
    "SAFE_BUILTINS",
    "AttrDict",
    "DeterministicASTValidator",
    "DowngradeRecord",
    "EvaluationResult",
    "ForbiddenExpressionError",
    "InvariantEvaluator",
    "InvariantSpec",
    "QuarantineManager",
    "wrap_attr_dict",
]
