"""Parallel Fork-Replay Engine Orchestrator.

Orchestrates K parallel independent branch executions from a fork point,
monitors budget limits, filters aborted branches, computes valid sample size N_valid,
and calculates 95% Wilson Score Confidence Intervals.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from budget import BudgetEnforcer
from fault_catalog import FaultSpec
from stats import (
    calculate_wilson_score,
    compute_n_min,
    compute_n_valid,
)


class ForkRunResult:
    """Encapsulates execution result, statistics, and Wilson Score CIs for a fork run."""

    def __init__(
        self,
        run_id: str,
        status: str,
        k: int,
        n_valid: int,
        n_min: int,
        n_miss: int = 0,
        n_infra: int = 0,
        n_budget: int = 0,
        reason: str | None = None,
        total_cost_usd: float = 0.0,
        violations: dict[str, dict[str, Any]] | None = None,
        branch_results: list[dict[str, Any]] | None = None,
    ) -> None:
        self.run_id = run_id
        self.status = status
        self.k = k
        self.n_valid = n_valid
        self.n_min = n_min
        self.n_miss = n_miss
        self.n_infra = n_infra
        self.n_budget = n_budget
        self.reason = reason
        self.total_cost_usd = total_cost_usd
        self.violations = violations or {}
        self.branch_results = branch_results or []

    def to_dict(self) -> dict[str, Any]:
        """Returns dictionary representation of ForkRunResult matching JSON schemas."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "reason": self.reason,
            "k": self.k,
            "n_valid": self.n_valid,
            "n_min": self.n_min,
            "n_miss": self.n_miss,
            "n_infra": self.n_infra,
            "n_budget": self.n_budget,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "violations": self.violations,
            "branch_results": self.branch_results,
        }


# Type alias for branch executor functions
BranchExecutorCallable = Callable[[int, FaultSpec], dict[str, Any]]


def default_simulated_branch_executor(
    branch_id: int,
    fault_spec: FaultSpec,
) -> dict[str, Any]:
    """Default simulated worker executing a branch with a given fault_spec."""
    # Base simulated cost
    cost_usd = 0.05
    # Simulated execution result
    return {
        "branch_id": branch_id,
        "status": "success",
        "fault_applied": fault_spec.to_dict(),
        "violations": ["INV-TIMEOUT-001"],
        "cost_usd": cost_usd,
        "tokens": 120,
        "duration_ms": 150,
    }


class ForkOrchestrator:
    """Orchestrates K parallel independent branch executions from a fork point."""

    def __init__(
        self,
        k: int = 20,
        budget_usd: float | None = None,
        budget_tokens: int | None = None,
        max_seconds: float | None = None,
        max_workers: int = 20,
    ) -> None:
        self.k = k
        self.max_workers = min(max_workers, k) if k > 0 else 1
        self.budget_enforcer = BudgetEnforcer(
            budget_usd=budget_usd,
            budget_tokens=budget_tokens,
            max_seconds=max_seconds,
        )

    def run_fork(
        self,
        fault_spec: FaultSpec | dict[str, Any],
        branch_executor: BranchExecutorCallable | None = None,
        run_id: str | None = None,
    ) -> ForkRunResult:
        """Runs K parallel branches from a fork point with the specified fault spec.

        Args:
            fault_spec: The fault spec object or dict to inject into each branch.
            branch_executor: Optional custom callable to execute each branch.
            run_id: Optional unique identifier for this fork run.

        Returns:
            ForkRunResult containing execution status, sample counts, and Wilson CIs.
        """
        run_id = run_id or f"fork_run_{uuid.uuid4().hex[:8]}"
        spec = (
            fault_spec
            if isinstance(fault_spec, FaultSpec)
            else FaultSpec.from_dict(fault_spec)
        )

        executor_func = branch_executor or default_simulated_branch_executor

        branch_outcomes: list[dict[str, Any]] = []

        def worker_wrapper(branch_id: int) -> dict[str, Any]:
            # Check if budget was already exceeded before running
            if self.budget_enforcer.is_aborted:
                return {
                    "branch_id": branch_id,
                    "status": "budget_aborted",
                    "reason": "budget_exceeded",
                    "violations": [],
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "duration_ms": 0,
                }

            try:
                res = executor_func(branch_id, spec)
            except Exception as exc:  # noqa: BLE001
                res = {
                    "branch_id": branch_id,
                    "status": "infra_error",
                    "error": str(exc),
                    "violations": [],
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "duration_ms": 0,
                }

            # Record usage in budget enforcer
            cost_usd = float(res.get("cost_usd", 0.0))
            tokens = int(res.get("tokens", 0))
            duration_s = float(res.get("duration_ms", 0)) / 1000.0

            budget_exceeded = self.budget_enforcer.record_usage(
                cost_usd=cost_usd,
                tokens=tokens,
                seconds=duration_s,
            )

            # If this run triggered budget abort, update status if not already set
            if budget_exceeded and res.get("status") != "budget_aborted":
                res["budget_exceeded_by_run"] = True

            return res

        # Run K branches in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(worker_wrapper, i) for i in range(self.k)]
            for fut in as_completed(futures):
                try:
                    outcome = fut.result()
                    branch_outcomes.append(outcome)
                except Exception as exc:  # noqa: BLE001
                    branch_outcomes.append(
                        {
                            "status": "infra_error",
                            "error": str(exc),
                            "violations": [],
                        }
                    )

        # Sort outcomes by branch_id for determinism
        branch_outcomes.sort(key=lambda x: x.get("branch_id", 0))

        # Calculate sample counts
        n_miss = sum(1 for b in branch_outcomes if b.get("status") == "cassette_miss")
        n_infra = sum(
            1 for b in branch_outcomes if b.get("status") in ("infra_error", "timeout")
        )
        n_budget = sum(1 for b in branch_outcomes if b.get("status") == "budget_aborted")

        n_valid = compute_n_valid(
            self.k, n_miss=n_miss, n_infra=n_infra, n_budget=n_budget
        )
        n_min = compute_n_min(self.k)

        total_cost = self.budget_enforcer.accumulated_usd

        # Check budget exceeded condition first
        if self.budget_enforcer.is_aborted:
            return ForkRunResult(
                run_id=run_id,
                status="budget_exceeded",
                k=self.k,
                n_valid=n_valid,
                n_min=n_min,
                n_miss=n_miss,
                n_infra=n_infra,
                n_budget=n_budget,
                reason=self.budget_enforcer.abort_reason or "budget_exceeded",
                total_cost_usd=total_cost,
                violations={},
                branch_results=branch_outcomes,
            )

        # Check sufficiency condition N_valid < N_min
        if n_valid < n_min:
            return ForkRunResult(
                run_id=run_id,
                status="inconclusive",
                k=self.k,
                n_valid=n_valid,
                n_min=n_min,
                n_miss=n_miss,
                n_infra=n_infra,
                n_budget=n_budget,
                reason="insufficient_valid_samples",
                total_cost_usd=total_cost,
                violations={},
                branch_results=branch_outcomes,
            )

        # Collect violations across valid branches
        violation_counts: dict[str, int] = {}
        for b in branch_outcomes:
            if b.get("status") == "success" and b.get("violations"):
                for inv_id in b["violations"]:
                    violation_counts[inv_id] = violation_counts.get(inv_id, 0) + 1

        violations_dict: dict[str, dict[str, Any]] = {}
        for inv_id, hits in violation_counts.items():
            rate = round(hits / n_valid, 3) if n_valid > 0 else 0.0
            ci_lower, ci_upper = calculate_wilson_score(hits, n_valid)
            violations_dict[inv_id] = {
                "hits": hits,
                "n_valid": n_valid,
                "violation_rate": rate,
                "wilson_ci": [ci_lower, ci_upper],
            }

        return ForkRunResult(
            run_id=run_id,
            status="completed",
            k=self.k,
            n_valid=n_valid,
            n_min=n_min,
            n_miss=n_miss,
            n_infra=n_infra,
            n_budget=n_budget,
            total_cost_usd=total_cost,
            violations=violations_dict,
            branch_results=branch_outcomes,
        )
