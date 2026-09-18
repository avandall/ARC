"""Escaped Bug Tracker & Quarterly Incident Metric Calculation (TASK-P4-003).

Provides incident tagging, false_negative catalog update, postmortem invariant suggestion generation,
and quarterly escaped bug rate calculation.
"""

from __future__ import annotations

import uuid
from typing import Any

from arc.control_plane.warehouse.db_store import DatabaseStore


class EscapedBugTracker:
    """Escaped Bug Tracker service for tagging incidents and calculating rates."""

    def __init__(self, db_store: DatabaseStore | None = None) -> None:
        self._db_store = db_store

    @property
    def db_store(self) -> DatabaseStore:
        return self._db_store or DatabaseStore.get_shared_instance()

    def tag_incident(
        self,
        trace_id: str,
        escaped_bug: bool = True,
        linked_invariant: str | None = None,
        root_cause: str = "",
        tagged_by: str = "engineer",
        quarter: str = "2026-Q3",
    ) -> dict[str, Any]:
        """Tags an incident as an escaped bug and updates catalog/miner suggestions.

        Args:
            trace_id: Target CTF trace ID. Must exist in the database.
            escaped_bug: Whether this incident is an escaped bug caused by an agent.
            linked_invariant: Optional invariant ID (e.g. INV-PAY-002) linked to this failure.
            root_cause: Detailed root cause description.
            tagged_by: User/engineer who tagged the incident.
            quarter: Target quarter (e.g. "2026-Q3").

        Returns:
            Dictionary containing the recorded incident bug metadata.

        Raises:
            ValueError: If trace_id is not found in the database.
        """
        trace = self.db_store.get_trace_by_id(trace_id)
        if not trace:
            raise ValueError("Trace ID not found")

        incident_id = f"inc_{uuid.uuid4().hex[:8]}"
        bug_record = {
            "incident_id": incident_id,
            "trace_id": trace_id,
            "linked_invariant": linked_invariant,
            "root_cause": root_cause,
            "tagged_by": tagged_by,
            "is_agent_caused": escaped_bug,
            "quarter": quarter,
        }

        # 1. Save incident to escaped_bugs table
        self.db_store.insert_escaped_bug(bug_record)

        # 2. Update catalog track record false_negative if linked_invariant exists
        if linked_invariant:
            self.db_store.increment_invariant_false_negative(linked_invariant)

        # 3. If no linked invariant, auto-generate candidate suggestion for Invariant Miner
        if not linked_invariant:
            cand_id = f"cand_pm_{trace_id[:8]}"
            suggestion = {
                "candidate_id": cand_id,
                "statement": f"Postmortem invariant suggestion for trace {trace_id}: {root_cause}",
                "category": "safety",
                "check_expr": "",
                "severity": "critical",
                "sources": [f"escaped_bug:{incident_id}"],
                "status": "pending",
            }
            self.db_store.insert_candidate(suggestion)

        return bug_record

    def calculate_quarterly_escaped_bug_rate(
        self,
        quarter: str | None = None,
        total_incidents: int | None = None,
    ) -> float:
        """Calculates quarterly escaped_bug_rate = number of escaped bugs / total agent incidents.

        Args:
            quarter: Target quarter filter (e.g. "2026-Q3").
            total_incidents: Optional explicit total incident count override.

        Returns:
            Escaped bug rate as a float (e.g. 0.20 for 20%).
        """
        bugs = self.db_store.list_escaped_bugs(quarter=quarter)
        agent_escaped_count = sum(1 for b in bugs if b.get("is_agent_caused", 1))

        if total_incidents is not None:
            denom = total_incidents
        else:
            # Fallback: total traces or total bugs
            traces = self.db_store.get_traces()
            denom = len(traces) if len(traces) > 0 else len(bugs)

        if denom == 0:
            return 0.0

        return round(agent_escaped_count / denom, 4)


def tag_incident(
    trace_id: str,
    escaped_bug: bool = True,
    linked_invariant: str | None = None,
    root_cause: str = "",
    tagged_by: str = "engineer",
    db_store: DatabaseStore | None = None,
) -> dict[str, Any]:
    """Top-level helper function to tag an incident."""
    tracker = EscapedBugTracker(db_store=db_store)
    return tracker.tag_incident(
        trace_id=trace_id,
        escaped_bug=escaped_bug,
        linked_invariant=linked_invariant,
        root_cause=root_cause,
        tagged_by=tagged_by,
    )


def calculate_quarterly_escaped_bug_rate(
    quarter: str | None = None,
    total_incidents: int | None = None,
    db_store: DatabaseStore | None = None,
) -> float:
    """Top-level helper function to calculate quarterly escaped bug rate."""
    tracker = EscapedBugTracker(db_store=db_store)
    return tracker.calculate_quarterly_escaped_bug_rate(
        quarter=quarter, total_incidents=total_incidents
    )
