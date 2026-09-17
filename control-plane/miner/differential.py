"""Differential Profiling Engine for Trace Invariant Mining (TASK-P3-003).

Compares an error trace against successful baseline traces to locate execution divergence
points while strictly enforcing reliable status_source labeling (§4.1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Reliable status sources per §4.1
RELIABLE_STATUS_SOURCES = {
    "human_triage",
    "reconciliation_webhook",
    "agent_self_report",
}

UNRELIABLE_STATUS_SOURCES = {
    "inferred_no_terminal_event",
}


@dataclass
class ProfilingResult:
    """Result of a differential profiling run comparing an error trace to baseline traces."""

    error_trace_id: str
    divergent_step: dict[str, Any] | None
    divergent_step_index: int | None
    divergence_reason: str
    filtered_baseline_count: int
    ignored_unreliable_count: int
    baseline_traces: list[dict[str, Any]] = field(default_factory=list)
    ignored_traces: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_trace_id": self.error_trace_id,
            "divergent_step": self.divergent_step,
            "divergent_step_index": self.divergent_step_index,
            "divergence_reason": self.divergence_reason,
            "filtered_baseline_count": self.filtered_baseline_count,
            "ignored_unreliable_count": self.ignored_unreliable_count,
        }


class DifferentialProfiler:
    """Differential Profiler comparing error traces with successful baseline traces (§4.1)."""

    def filter_reliable_traces(
        self,
        traces: list[dict[str, Any]],
        for_success_baseline: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Filters input traces, ignoring any traces with unreliable status_source.

        Per §4.1, inferred_no_terminal_event is never used for success baselines.
        """
        reliable: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []

        for trace in traces:
            status_src = trace.get("status_source", "unknown")
            if status_src in UNRELIABLE_STATUS_SOURCES:
                ignored.append(trace)
                logger.info(
                    f"Ignoring trace {trace.get('trace_id')} due to unreliable status_source: {status_src}"
                )
            elif for_success_baseline and status_src not in {"human_triage", "reconciliation_webhook"}:
                # For success baseline in differential profiling, agent_self_report and inferred are unreliable
                ignored.append(trace)
            elif status_src in RELIABLE_STATUS_SOURCES:
                reliable.append(trace)
            else:
                ignored.append(trace)

        return reliable, ignored

    def profile(
        self,
        error_trace: dict[str, Any],
        baseline_traces: list[dict[str, Any]],
    ) -> ProfilingResult:
        """Profiles 1 error trace against baseline success traces to identify divergent steps."""
        error_trace_id = error_trace.get("trace_id", "unknown_err_trace")

        # Filter baseline traces to retain only reliable status_source (§4.1)
        reliable_baselines, ignored_baselines = self.filter_reliable_traces(
            baseline_traces,
            for_success_baseline=True,
        )

        error_steps = error_trace.get("steps", [])

        if not reliable_baselines:
            return ProfilingResult(
                error_trace_id=error_trace_id,
                divergent_step=None,
                divergent_step_index=None,
                divergence_reason="No reliable baseline traces available after filtering.",
                filtered_baseline_count=0,
                ignored_unreliable_count=len(ignored_baselines),
                baseline_traces=[],
                ignored_traces=ignored_baselines,
            )

        # Collect baseline step patterns by index or action sequence
        baseline_step_patterns: list[set[str]] = []
        max_baseline_len = max(len(t.get("steps", [])) for t in reliable_baselines)

        for idx in range(max_baseline_len):
            actions_at_idx: set[str] = set()
            for b_trace in reliable_baselines:
                b_steps = b_trace.get("steps", [])
                if idx < len(b_steps):
                    action_key = b_steps[idx].get("action") or b_steps[idx].get("name") or b_steps[idx].get("type")
                    if action_key:
                        actions_at_idx.add(str(action_key))
            baseline_step_patterns.append(actions_at_idx)

        # Identify divergent step in error_trace
        divergent_step: dict[str, Any] | None = None
        divergent_step_idx: int | None = None
        divergence_reason = "No divergence found"

        for idx, err_step in enumerate(error_steps):
            err_action = str(err_step.get("action") or err_step.get("name") or err_step.get("type") or "")
            err_status = str(err_step.get("status", "")).lower()

            # Check if step status is error/timeout/retry or action not in baseline
            is_error_status = err_status in {"error", "timeout", "failed", "retry", "duplicate_refund", "double_refund"}
            is_retry_action = "retry" in err_action.lower() or "timeout" in err_action.lower()

            # Divergence condition 1: step beyond baseline length
            if idx >= len(baseline_step_patterns):
                divergent_step = err_step
                divergent_step_idx = idx
                divergence_reason = f"Extra step at index {idx} not present in baseline success traces ({err_action})"
                break

            # Divergence condition 2: action not seen in baseline at this step index
            baseline_actions = baseline_step_patterns[idx]
            if baseline_actions and err_action not in baseline_actions:
                divergent_step = err_step
                divergent_step_idx = idx
                divergence_reason = f"Divergent action '{err_action}' at step {idx} (expected one of {baseline_actions})"
                break

            # Divergence condition 3: error/retry step following a timeout or failure
            if is_error_status or is_retry_action:
                divergent_step = err_step
                divergent_step_idx = idx
                divergence_reason = f"Divergent step status/action '{err_action}' ({err_status}) at step {idx}"
                break

        # Fallback: if no step matched rules above, select first step with status != success
        if divergent_step is None and error_steps:
            for idx, err_step in enumerate(error_steps):
                if err_step.get("status") not in {"success", "completed", "ok"}:
                    divergent_step = err_step
                    divergent_step_idx = idx
                    divergence_reason = f"Divergent step status '{err_step.get('status')}' at index {idx}"
                    break

        return ProfilingResult(
            error_trace_id=error_trace_id,
            divergent_step=divergent_step,
            divergent_step_index=divergent_step_idx,
            divergence_reason=divergence_reason,
            filtered_baseline_count=len(reliable_baselines),
            ignored_unreliable_count=len(ignored_baselines),
            baseline_traces=reliable_baselines,
            ignored_traces=ignored_baselines,
        )
