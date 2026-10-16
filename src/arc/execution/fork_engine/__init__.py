"""ARC Parallel Fork-Replay & Chaos Fault Injection Engine.

Dispatches K parallel independent branch executions from a fork point,
monitors budget limits, computes 95% Wilson Score Confidence Intervals,
and minimizes failure traces via Delta-Debugging (ddmin).

Classes:
    ForkOrchestrator: Dispatches and aggregates K parallel branch executions.
    ForkRunResult: Encapsulates execution statistics, sample counts, and Wilson CIs.
    FaultInjector: Intercepts tool calls and applies infrastructure or semantic faults.
    FaultCatalog: Specification registry managing single and compound fault chains.
    FaultSpec: Fault specification defining target step, tool, type, and parameters.
    FaultType: Enumeration of supported fault types across Groups A, B, and C.
    GateEvaluator: Evaluates simulation verdicts against baseline Wilson score intervals.
    CIGateExitCode: Standard POSIX exit codes (0, 1, 2, 3) for CI pipelines.
    BudgetEnforcer: Monitors and enforces USD, token, and runtime ceilings.
    BudgetExceededException: Exception raised when execution budget is breached.
    RegressionTestGenerator: Generates runnable pytest regression files from YAML reproducers.

Functions:
    ddmin: Minimizes a fault sequence to the smallest subset reproducing a failure.
    export_minimal_reproducer_yaml: Exports minimal reproducer YAML artifact.
    calculate_wilson_score: Computes Wilson score interval for binomial proportions.
"""

from __future__ import annotations

from arc.execution.fork_engine.budget import (
    BudgetEnforcer,
    BudgetExceededException,
)
from arc.execution.fork_engine.delta_debugging import (
    IrreproducibleBugError,
    ddmin,
)
from arc.execution.fork_engine.fault_catalog import (
    CONCURRENCY_FAULTS,
    INFRA_FAULTS,
    SEMANTIC_FAULTS,
    FaultCatalog,
    FaultSpec,
    FaultType,
)
from arc.execution.fork_engine.gate_evaluator import (
    CIGateExitCode,
    GateEvaluationResult,
    GateEvaluator,
    check_wilson_overlap,
)
from arc.execution.fork_engine.injector import FaultInjector
from arc.execution.fork_engine.orchestrator import (
    ForkOrchestrator,
    ForkRunResult,
    default_dry_run_executor,
)
from arc.execution.fork_engine.regression_generator import (
    RegressionTestGenerator,
    generate_regression_test,
)
from arc.execution.fork_engine.reproducer_export import (
    export_minimal_reproducer_yaml,
)
from arc.execution.fork_engine.stats import (
    calculate_wilson_score,
    compute_n_min,
    compute_n_valid,
    is_sample_sufficient,
    summarize_stat_results,
)

__all__ = [
    "CONCURRENCY_FAULTS",
    "INFRA_FAULTS",
    "SEMANTIC_FAULTS",
    "BudgetEnforcer",
    "BudgetExceededException",
    "CIGateExitCode",
    "FaultCatalog",
    "FaultInjector",
    "FaultSpec",
    "FaultType",
    "ForkOrchestrator",
    "ForkRunResult",
    "GateEvaluationResult",
    "GateEvaluator",
    "IrreproducibleBugError",
    "RegressionTestGenerator",
    "calculate_wilson_score",
    "check_wilson_overlap",
    "compute_n_min",
    "compute_n_valid",
    "default_dry_run_executor",
    "ddmin",
    "export_minimal_reproducer_yaml",
    "generate_regression_test",
    "is_sample_sufficient",
    "summarize_stat_results",
]
