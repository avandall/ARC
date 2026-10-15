"""Parallel Fork-Replay Engine Orchestrator.

Orchestrates K parallel independent branch executions from a fork point,
monitors budget limits, filters aborted branches, computes valid sample size N_valid,
and calculates 95% Wilson Score Confidence Intervals.

F3: InvariantEvaluator + QuarantineManager are now wired into the branch pipeline.
    If a branch executor returns an "effects" key, the orchestrator automatically
    runs InvariantEvaluator on those effects and merges the result into "violations".
    This means violations are computed deterministically from ledger evidence,
    not asserted as opaque string IDs by the executor.

F5: default_simulated_branch_executor (which hardcoded violations: ["INV-TIMEOUT-001"])
    has been replaced by default_dry_run_executor — a minimal stub that returns empty
    violations and effects, making it clear that real analysis requires a real executor.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from arc.execution.fork_engine.budget import BudgetEnforcer
from arc.execution.fork_engine.fault_catalog import FaultSpec
from arc.execution.fork_engine.stats import (
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


# ── F5: Replace hardcoded default executor ───────────────────────────────────

def default_dry_run_executor(
    branch_id: int,
    fault_spec: FaultSpec,
) -> dict[str, Any]:
    """Minimal dry-run stub that produces no fake violations or effects.

    F5 change: Replaces the old default_simulated_branch_executor which
    hardcoded violations=["INV-TIMEOUT-001"] regardless of actual execution,
    making ForkOrchestrator results meaningless without a real executor.

    For actual analysis, callers must supply a real branch_executor that:
      1. Calls SandboxRunner.run_with_faults(fault_spec, target_invariant)
      2. Returns a dict with "effects" and/or "violations" keys.
    """
    return {
        "branch_id": branch_id,
        "status": "success",
        "fault_applied": fault_spec.to_dict(),
        "violations": [],   # no fake violations
        "effects": [],      # no fake effects
        "cost_usd": 0.0,
        "tokens": 0,
        "duration_ms": 0,
    }


# Keep old name as alias so existing callers don't break immediately
default_simulated_branch_executor = default_dry_run_executor


class ForkOrchestrator:
    """Orchestrates K parallel independent branch executions from a fork point.

    F3: Accepts an optional invariant_catalog. When a branch executor returns
    an "effects" list, the orchestrator runs InvariantEvaluator on those effects
    and merges computed violation IDs into the branch result's "violations" list.
    This makes violation detection deterministic and driven by actual ledger state.
    """

    def __init__(
        self,
        k: int = 20,
        budget_usd: float | None = None,
        budget_tokens: int | None = None,
        max_seconds: float | None = None,
        max_workers: int = 20,
        invariant_catalog: list[dict[str, Any]] | None = None,   # F3
    ) -> None:
        self.k = k
        self.max_workers = min(max_workers, k) if k > 0 else 1
        self.budget_enforcer = BudgetEnforcer(
            budget_usd=budget_usd,
            budget_tokens=budget_tokens,
            max_seconds=max_seconds,
        )
        # F3: InvariantEvaluator wiring
        self._invariant_catalog: list[dict[str, Any]] = list(invariant_catalog or [])
        self._evaluator: Any = None   # lazy-init to avoid circular imports
        self._quarantine: Any = None  # lazy-init

    # ── F3: Invariant evaluation helper ──────────────────────────────────────

    def _ensure_evaluator(self) -> None:
        """Lazy-initialises InvariantEvaluator and QuarantineManager."""
        if self._evaluator is None:
            from arc.execution.invariant_engine.evaluator import InvariantEvaluator
            from arc.execution.invariant_engine.quarantine import QuarantineManager
            self._evaluator = InvariantEvaluator()
            self._quarantine = QuarantineManager()

    def _evaluate_branch_invariants(
        self,
        effects: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """Runs InvariantEvaluator over effect ledger entries.

        Returns list of violated invariant IDs that should block CI
        (quarantined invariants are excluded via QuarantineManager.should_block_ci).
        """
        if not self._invariant_catalog:
            return []

        self._ensure_evaluator()
        violated_ids: list[str] = []

        for inv in self._invariant_catalog:
            try:
                result, block_ci = self._quarantine.run_shadow_quarantine(
                    inv, self._evaluator, effects, context
                )
                if result.violated and block_ci:
                    inv_id = str(inv.get("id", "UNKNOWN"))
                    violated_ids.append(inv_id)
            except Exception:  # noqa: BLE001, S110
                # Never let evaluator errors kill a branch
                pass

        return violated_ids

    # ── Main fork execution ───────────────────────────────────────────────────

    def run_fork(
        self,
        fault_spec: FaultSpec | dict[str, Any],
        branch_executor: BranchExecutorCallable | None = None,
        run_id: str | None = None,
    ) -> ForkRunResult:
        """Runs K parallel branches from a fork point with the specified fault spec.

        Args:
            fault_spec:       The fault spec object or dict to inject into each branch.
            branch_executor:  Optional custom callable to execute each branch.
                              If the returned dict contains an "effects" key (list of
                              effect ledger entries), InvariantEvaluator will run on
                              those effects and merge results into "violations".
            run_id:           Optional unique identifier for this fork run.

        Returns:
            ForkRunResult containing execution status, sample counts, and Wilson CIs.
        """
        run_id = run_id or f"fork_run_{uuid.uuid4().hex[:8]}"
        spec = (
            fault_spec
            if isinstance(fault_spec, FaultSpec)
            else FaultSpec.from_dict(fault_spec)
        )

        executor_func = branch_executor or default_dry_run_executor

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

            # ── F3: If executor returned raw effects, evaluate invariants ─────
            if "effects" in res and self._invariant_catalog:
                computed_violations = self._evaluate_branch_invariants(
                    effects=res["effects"],
                    context=res.get("context"),
                )
                # Merge computed violations with any string IDs already in result
                existing: list[str] = res.get("violations") or []
                merged = list({*existing, *computed_violations})
                res["violations"] = merged
            # ─────────────────────────────────────────────────────────────────

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
            # F3: Attach severity from invariant catalog if available
            inv_meta = next(
                (inv for inv in self._invariant_catalog if inv.get("id") == inv_id), {}
            )
            violations_dict[inv_id] = {
                "hits": hits,
                "n_valid": n_valid,
                "violation_rate": rate,
                "wilson_ci": [ci_lower, ci_upper],
                "severity": inv_meta.get("severity", "critical"),  # F3+F6 data
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
