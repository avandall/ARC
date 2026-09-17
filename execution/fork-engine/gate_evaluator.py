"""CI Gate Evaluator module.

Evaluates fork-replay execution results against baseline Wilson Score CIs,
monitors budget limits and infrastructure failures, and determines POSIX exit codes (0/1/2/3).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from enum import IntEnum
from typing import Any

# Ensure execution/fork-engine directory is in sys.path if not present
fork_engine_dir = os.path.dirname(os.path.abspath(__file__))
if fork_engine_dir not in sys.path:
    sys.path.insert(0, fork_engine_dir)

try:
    from budget import BudgetExceededException
    from fault_catalog import FaultCatalog, FaultSpec
    from orchestrator import ForkOrchestrator, ForkRunResult
except ImportError:
    from execution.fork_engine.budget import BudgetExceededException  # type: ignore[no-redef]
    from execution.fork_engine.fault_catalog import (  # type: ignore[no-redef]
        FaultCatalog,
        FaultSpec,
    )
    from execution.fork_engine.orchestrator import (  # type: ignore[no-redef]
        ForkOrchestrator,
        ForkRunResult,
    )


class CIGateExitCode(IntEnum):
    """Standard POSIX exit codes for CI Gate (§11.1)."""

    SUCCESS = 0
    CRITICAL_VIOLATION = 1
    BUDGET_EXCEEDED = 2
    INFRA_ERROR = 3


class GateEvaluationResult:
    """Encapsulates CI Gate evaluation summary and exit code."""

    def __init__(
        self,
        exit_code: CIGateExitCode | int,
        status: str,
        profile: str,
        k: int,
        reason: str,
        violations: dict[str, dict[str, Any]] | None = None,
        total_cost_usd: float = 0.0,
        run_result: ForkRunResult | None = None,
    ) -> None:
        self.exit_code = CIGateExitCode(exit_code)
        self.status = status
        self.profile = profile
        self.k = k
        self.reason = reason
        self.violations = violations or {}
        self.total_cost_usd = total_cost_usd
        self.run_result = run_result

    def to_dict(self) -> dict[str, Any]:
        """Returns dictionary representation of GateEvaluationResult."""
        return {
            "exit_code": int(self.exit_code),
            "status": self.status,
            "profile": self.profile,
            "k": self.k,
            "reason": self.reason,
            "violations": self.violations,
            "total_cost_usd": round(self.total_cost_usd, 4),
        }


def check_wilson_overlap(
    ci_a: tuple[float, float] | list[float],
    ci_b: tuple[float, float] | list[float],
) -> bool:
    """Checks if two Wilson confidence intervals overlap.

    Returns True if max(A_lower, B_lower) <= min(A_upper, B_upper).
    """
    a_low, a_high = float(ci_a[0]), float(ci_a[1])
    b_low, b_high = float(ci_b[0]), float(ci_b[1])
    return max(a_low, b_low) <= min(a_high, b_high)


class GateEvaluator:
    """Evaluates CI gate runs against statistical confidence intervals and budget limits."""

    def __init__(
        self,
        profile: str = "smoke",
        budget_usd: float | None = None,
        baseline_ci: tuple[float, float] | list[float] = (0.0, 0.0),
    ) -> None:
        self.profile = profile.lower()
        self.budget_usd = budget_usd
        self.baseline_ci = (float(baseline_ci[0]), float(baseline_ci[1]))

        # Profile configurations (§11.1)
        if self.profile == "smoke":
            self.k = 3
        elif self.profile == "full":
            self.k = 20
        else:
            self.k = 3

    def evaluate(
        self,
        orchestrator_runner: Callable[[], ForkRunResult] | None = None,
        branch_executor: Callable[[int, FaultSpec], dict[str, Any]] | None = None,
        fault_catalog: FaultCatalog | None = None,
        trace_id: str | None = None,
    ) -> GateEvaluationResult:
        """Executes gate evaluation and returns GateEvaluationResult with exit code."""
        # Catch Infra errors early or during execution
        try:
            if orchestrator_runner is not None:
                run_result = orchestrator_runner()
            else:
                catalog = fault_catalog or FaultCatalog()
                faults = catalog.get_all_faults()
                default_spec = (
                    faults[0]
                    if faults
                    else FaultSpec(at_step=1, fault_type="timeout_after_commit")
                )
                orchestrator = ForkOrchestrator(
                    k=self.k,
                    budget_usd=self.budget_usd,
                )
                run_result = orchestrator.run_fork(
                    fault_spec=default_spec,
                    branch_executor=branch_executor,
                    run_id=trace_id or "trace_ci_gate",
                )
        except (ConnectionRefusedError, ConnectionError, OSError, RuntimeError) as e:
            err_str = str(e).lower()
            if isinstance(e, (ConnectionRefusedError, ConnectionError)) or any(
                term in err_str for term in ["docker", "connection", "refused", "database", "socket"]
            ):
                return GateEvaluationResult(
                    exit_code=CIGateExitCode.INFRA_ERROR,
                    status="INFRA_ERROR",
                    profile=self.profile,
                    k=self.k,
                    reason=f"Infrastructure failure: {e}",
                )
            raise
        except BudgetExceededException as e:
            return GateEvaluationResult(
                exit_code=CIGateExitCode.BUDGET_EXCEEDED,
                status="BUDGET_EXCEEDED",
                profile=self.profile,
                k=self.k,
                reason=f"Budget exceeded: {e}",
            )
        except Exception as e:
            err_str = str(e).lower()
            if any(term in err_str for term in ["docker", "connection", "refused", "database", "socket"]):
                return GateEvaluationResult(
                    exit_code=CIGateExitCode.INFRA_ERROR,
                    status="INFRA_ERROR",
                    profile=self.profile,
                    k=self.k,
                    reason=f"Infrastructure failure: {e}",
                )
            raise

        # Check run_result statuses
        if run_result.status in ("infra_error", "docker_failure") or (
            run_result.n_infra > 0 and run_result.n_valid == 0
        ):
            return GateEvaluationResult(
                exit_code=CIGateExitCode.INFRA_ERROR,
                status="INFRA_ERROR",
                profile=self.profile,
                k=self.k,
                reason=run_result.reason or "Infrastructure failure during branch execution",
                run_result=run_result,
            )

        if (
            run_result.status == "budget_exceeded"
            or run_result.n_budget > 0
            or (self.budget_usd is not None and run_result.total_cost_usd > self.budget_usd)
        ):
            return GateEvaluationResult(
                exit_code=CIGateExitCode.BUDGET_EXCEEDED,
                status="BUDGET_EXCEEDED",
                profile=self.profile,
                k=self.k,
                reason=run_result.reason or "Budget limit reached before evaluation completion",
                total_cost_usd=run_result.total_cost_usd,
                run_result=run_result,
            )

        # Evaluate critical invariant violations against baseline CI
        critical_violations: dict[str, dict[str, Any]] = {}
        has_confirmed_critical_violation = False

        for inv_id, vdata in run_result.violations.items():
            severity = vdata.get("severity", "critical")
            ci = vdata.get("wilson_ci", [0.0, 0.0])

            overlaps = check_wilson_overlap(ci, self.baseline_ci)
            vdata_entry = dict(vdata)
            vdata_entry["overlaps_baseline"] = overlaps

            if severity == "critical":
                critical_violations[inv_id] = vdata_entry
                if not overlaps:
                    has_confirmed_critical_violation = True

        if has_confirmed_critical_violation:
            return GateEvaluationResult(
                exit_code=CIGateExitCode.CRITICAL_VIOLATION,
                status="FAIL",
                profile=self.profile,
                k=self.k,
                reason="Confirmed critical invariant violation detected (Wilson CI does not overlap baseline)",
                violations=critical_violations,
                total_cost_usd=run_result.total_cost_usd,
                run_result=run_result,
            )

        return GateEvaluationResult(
            exit_code=CIGateExitCode.SUCCESS,
            status="PASS",
            profile=self.profile,
            k=self.k,
            reason="No critical violations detected or CI overlaps baseline",
            violations=critical_violations,
            total_cost_usd=run_result.total_cost_usd,
            run_result=run_result,
        )
