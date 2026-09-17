"""Quarantine Engine & Shadow Mode Execution (TASK-P3-001).

Manages invariant quarantine state transitions and shadow mode execution according to §8.4.
Invariants with low precision (< 0.50 after >= 10 triaged runs) are automatically downgraded
to 'quarantined'. Quarantined invariants continue to run in shadow mode and update track records,
but never block CI builds (should_block_ci returns False).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from arc.execution.invariant_engine.evaluator import (
    EvaluationResult,
    InvariantEvaluator,
    InvariantSpec,
)


@dataclass
class DowngradeRecord:
    """Record of status downgrade event for an invariant."""

    timestamp: float
    from_status: str
    to_status: str
    reason: str
    precision: float
    triaged: int


@dataclass
class QuarantineManager:
    """Manages invariant status transitions, auto-quarantine, and shadow mode execution."""

    min_triaged: int = 10
    precision_threshold: float = 0.50
    downgrade_history: list[DowngradeRecord] = field(default_factory=list)

    def auto_quarantine_check(self, invariant: InvariantSpec | dict[str, Any]) -> bool:
        """Checks if invariant precision has dropped below threshold after min_triaged runs.

        If precision < 0.50 and triaged >= 10, automatically downgrades status from 'active' to 'quarantined'
        and records downgrade history.
        """
        if isinstance(invariant, dict):
            track_record = invariant.setdefault("track_record", {})
            status = invariant.get("status", "active")
        else:
            track_record = invariant.track_record
            status = invariant.status

        triaged = track_record.get("triaged", 0)
        precision = track_record.get("precision", 1.0)

        # Re-compute precision if triaged > 0 and confirmed_real_bug is present
        if triaged > 0 and "confirmed_real_bug" in track_record and "precision" not in track_record:
            confirmed = track_record.get("confirmed_real_bug", 0)
            precision = confirmed / triaged
            track_record["precision"] = precision

        if triaged >= self.min_triaged and precision < self.precision_threshold and status == "active":
            new_status = "quarantined"
            reason = (
                f"Auto-quarantined: Precision {precision:.2f} < threshold {self.precision_threshold:.2f} "
                f"after {triaged} triaged runs"
            )

            record = DowngradeRecord(
                timestamp=time.time(),
                from_status=status,
                to_status=new_status,
                reason=reason,
                precision=precision,
                triaged=triaged,
            )
            self.downgrade_history.append(record)

            if isinstance(invariant, dict):
                invariant["status"] = new_status
                invariant.setdefault("downgrade_history", []).append(record.__dict__)
                track_record["status"] = new_status
            else:
                invariant.status = new_status
                track_record["status"] = new_status
                invariant.downgrade_history.append(record.__dict__)

            return True

        return False

    def should_block_ci(
        self,
        invariant: InvariantSpec | dict[str, Any],
        evaluation_result: EvaluationResult,
    ) -> bool:
        """Determines if an invariant violation should block the CI build.

        Quarantined and deprecated invariants NEVER block CI builds (returns False).
        Active invariants with violated == True return True.
        """
        status = invariant.status if isinstance(invariant, InvariantSpec) else invariant.get("status", "active")

        if status in ("quarantined", "deprecated"):
            return False

        return evaluation_result.violated

    def run_shadow_quarantine(
        self,
        invariant: InvariantSpec | dict[str, Any],
        evaluator: InvariantEvaluator,
        effects: list[dict[str, Any] | Any],
        context: dict[str, Any] | Any | None = None,
    ) -> tuple[EvaluationResult, bool]:
        """Runs invariant evaluation in shadow mode (even if quarantined).

        Calculates result, updates track_record.triaged, runs auto_quarantine_check,
        and returns (evaluation_result, should_block_ci).
        """
        result = evaluator.evaluate(invariant, effects, context)

        if isinstance(invariant, dict):
            track_record = invariant.setdefault("track_record", {})
        else:
            track_record = invariant.track_record

        track_record["triaged"] = track_record.get("triaged", 0) + 1
        if result.violated:
            track_record["confirmed_real_bug"] = track_record.get("confirmed_real_bug", 0) + 1
        else:
            track_record["false_positive"] = track_record.get("false_positive", 0) + 1

        triaged = track_record["triaged"]
        confirmed = track_record.get("confirmed_real_bug", 0)
        track_record["precision"] = confirmed / triaged if triaged > 0 else 1.0

        self.auto_quarantine_check(invariant)

        block_ci = self.should_block_ci(invariant, result)
        return result, block_ci
