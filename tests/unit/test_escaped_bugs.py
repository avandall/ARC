"""Unit tests for Escaped Bug Tracker & Incident Tagging (TASK-P4-003)."""

import pytest
from typer.testing import CliRunner

from arc.cli.main import app
from arc.control_plane.warehouse.db_store import DatabaseStore
from arc.control_plane.warehouse.escaped_bugs import (
    EscapedBugTracker,
    calculate_quarterly_escaped_bug_rate,
    tag_incident,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_clean_db():
    """Resets shared DatabaseStore instance before each test."""
    DatabaseStore.reset_shared_instance()
    db = DatabaseStore.get_shared_instance()
    yield db


def test_tag_incident_escaped_bug(setup_clean_db):
    """Happy Path 1: Run `arc incidents tag --trace 0af765... --escaped-bug --linked-invariant INV-PAY-002 --root-cause 'Missing idempotency header'`.

    Record is stored in `escaped_bugs` table and `false_negative` count of `INV-PAY-002` in catalog is incremented by 1.
    """
    db = setup_clean_db
    trace_id = "0af7651916cd43dd8448eb211c80319c"

    # Pre-populate trace metadata
    db.insert_trace(
        trace_meta={
            "trace_id": trace_id,
            "agent_name": "refund-agent",
            "agent_version": "1.0.0",
            "model_provider": "anthropic",
            "model_id": "claude-sonnet-4-6",
            "determinism_lvl": "L2",
            "outcome_status": "completed",
            "status_source": "reconciliation_webhook",
            "redaction_key_id": "default",
        },
        steps_meta=[],
        effects_meta=[],
    )

    result = runner.invoke(
        app,
        [
            "incidents",
            "tag",
            "--trace",
            trace_id,
            "--escaped-bug",
            "--linked-invariant",
            "INV-PAY-002",
            "--root-cause",
            "Missing idempotency header",
        ],
    )

    assert result.exit_code == 0, f"Command failed output: {result.output}"

    bugs = db.list_escaped_bugs()
    assert len(bugs) == 1
    assert bugs[0]["trace_id"] == trace_id
    assert bugs[0]["linked_invariant"] == "INV-PAY-002"
    assert bugs[0]["root_cause"] == "Missing idempotency header"

    fn_count = db.get_invariant_false_negative("INV-PAY-002")
    assert fn_count == 1


def test_quarterly_escaped_bug_rate_calculation(setup_clean_db):
    """Happy Path 2: Ingest 10 incidents in a quarter, 2 of which are tagged as agent-caused escaped bugs.

    Metric calculation returns `escaped_bug_rate = 0.20`.
    """
    db = setup_clean_db
    quarter = "2026-Q3"

    # Seed 10 traces & incidents
    for i in range(10):
        t_id = f"trace_q3_{i:02d}"
        db.insert_trace(
            trace_meta={
                "trace_id": t_id,
                "agent_name": "refund-agent",
                "agent_version": "1.0.0",
                "model_provider": "anthropic",
                "model_id": "claude-sonnet-4-6",
                "determinism_lvl": "L2",
                "outcome_status": "completed",
                "status_source": "reconciliation_webhook",
                "redaction_key_id": "default",
            },
            steps_meta=[],
            effects_meta=[],
        )

        is_escaped = i < 2  # First 2 are agent caused escaped bugs
        db.insert_escaped_bug({
            "incident_id": f"inc_q3_{i:02d}",
            "trace_id": t_id,
            "root_cause": f"Root cause {i}",
            "tagged_by": "engineer",
            "is_agent_caused": is_escaped,
            "quarter": quarter,
        })

    tracker = EscapedBugTracker(db_store=db)
    rate = tracker.calculate_quarterly_escaped_bug_rate(quarter=quarter, total_incidents=10)
    assert rate == pytest.approx(0.20)

    # Top level helper check
    rate_helper = calculate_quarterly_escaped_bug_rate(
        quarter=quarter, total_incidents=10, db_store=db
    )
    assert rate_helper == pytest.approx(0.20)


def test_tag_incident_with_non_existent_trace_id(setup_clean_db):
    """Edge Case 1: Attempt to tag an incident with a non-existent trace_id in the database.

    Command returns error code and message `"Trace ID not found"`.
    """
    result = runner.invoke(
        app,
        [
            "incidents",
            "tag",
            "--trace",
            "non_existent_trace_99999",
            "--escaped-bug",
            "--root-cause",
            "Invalid trace test",
        ],
    )

    assert result.exit_code != 0
    assert "Trace ID not found" in result.output


def test_tag_incident_without_linked_invariant(setup_clean_db):
    """Edge Case 2: Tag a new incident without an existing linked invariant (`linked-invariant=None`).

    System persists record and generates suggestion for Invariant Miner postmortem extraction.
    """
    db = setup_clean_db
    trace_id = "trace_new_postmortem_123"

    db.insert_trace(
        trace_meta={
            "trace_id": trace_id,
            "agent_name": "refund-agent",
            "agent_version": "1.0.0",
            "model_provider": "anthropic",
            "model_id": "claude-sonnet-4-6",
            "determinism_lvl": "L2",
            "outcome_status": "completed",
            "status_source": "reconciliation_webhook",
            "redaction_key_id": "default",
        },
        steps_meta=[],
        effects_meta=[],
    )

    # Tag incident without linked invariant
    bug = tag_incident(
        trace_id=trace_id,
        escaped_bug=True,
        linked_invariant=None,
        root_cause="Unobserved race condition in database transaction",
        db_store=db,
    )

    assert bug["trace_id"] == trace_id
    assert bug["linked_invariant"] is None

    # Check that candidate suggestion for miner was created
    candidates = db.list_candidates(status="pending")
    assert len(candidates) >= 1
    miner_candidate = next(
        (c for c in candidates if c["candidate_id"] == f"cand_pm_{trace_id[:8]}"), None
    )
    assert miner_candidate is not None
    assert "Postmortem invariant suggestion" in miner_candidate["statement"]
    assert "Unobserved race condition" in miner_candidate["statement"]
