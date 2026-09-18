import json
import pathlib
import subprocess

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def get_validator(schema_name: str) -> Draft202012Validator:
    schema_dir = pathlib.Path("schemas/json")
    registry = Registry()
    for p in schema_dir.glob("*.json"):
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
            resource = Resource.from_contents(s)
            registry = registry.with_resource(p.name, resource)
            if "$id" in s:
                registry = registry.with_resource(s["$id"], resource)

    with open(schema_dir / schema_name, encoding="utf-8") as f:
        target_schema = json.load(f)

    return Draft202012Validator(target_schema, registry=registry)


def test_ctf_v1_valid_payload():
    """Happy Path 1: Validate sample valid CTF v1.0 payload with complete metadata."""
    validator = get_validator("ctf_v1.json")
    payload = {
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "session_id": "sess_9f21",
        "agent": {
            "name": "refund-agent",
            "version": "2.14.0",
            "git_sha": "a3f91c2"
        },
        "model": {
            "provider": "anthropic",
            "model_id": "claude-sonnet-4-6",
            "params": {
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 42,
                "max_tokens": 4096
            }
        },
        "started_at": "2026-09-14T09:12:04.221Z",
        "determinism_level": "L2",
        "steps": [
            {
                "step_id": 7,
                "kind": "tool_call",
                "t_virtual_ms": 5120,
                "parent_step": 6,
                "request": {
                    "tool": "issue_refund",
                    "args_ref": "sha256:be31...",
                    "idempotency_key": "ord_8842:refund:1",
                    "declared_mutating": True,
                    "scope": ["payments:write"]
                },
                "response": {
                    "status": "ok",
                    "body_ref": "sha256:7c02...",
                    "latency_ms": 940
                },
                "state_snapshot_ref": "sha256:9ab1...",
                "forkable": True,
                "fork_reasons": ["mutating_call"]
            }
        ],
        "effects": [
            {
                "effect_id": "eff_003",
                "step_id": 7,
                "type": "financial.refund",
                "resource": "order:8842",
                "delta": {"amount_cents": -4599, "currency": "USD"},
                "reversible": False,
                "idempotency_key": "ord_8842:refund:1",
                "observed_at_step": 7
            }
        ],
        "outcome": {
            "outcome_status": "completed",
            "status_source": "reconciliation_webhook",
            "cost_usd": 0.084,
            "wall_ms": 8412
        }
    }
    validator.validate(payload)


def test_postgresql_ddl_tables_and_rls_creation():
    """Happy Path 2: Execute schemas/sql/001_initial_schema.sql script and verify 7 tables + RLS policy."""
    sql_script = pathlib.Path("schemas/sql/001_initial_schema.sql")
    assert sql_script.exists(), "001_initial_schema.sql file missing"

    # Ensure test database exists
    subprocess.run(
        ["psql", "-h", "localhost", "-U", "postgres", "-c", "CREATE DATABASE arc_test;"],
        capture_output=True,
        text=True,
        check=False
    )

    # Run DDL migration
    res = subprocess.run(
        ["psql", "-h", "localhost", "-U", "postgres", "-d", "arc_test", "-f", str(sql_script)],
        capture_output=True,
        text=True,
        check=True
    )
    assert res.returncode == 0

    # Query created tables
    res_tables = subprocess.run(
        [
            "psql", "-h", "localhost", "-U", "postgres", "-d", "arc_test", "-t", "-c",
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"
        ],
        capture_output=True,
        text=True,
        check=True
    )
    tables = [t.strip() for t in res_tables.stdout.splitlines() if t.strip()]

    expected_tables = {
        "traces", "steps", "effects", "fork_runs",
        "invariant_candidates", "rejected_candidates", "escaped_bugs"
    }
    for expected in expected_tables:
        assert expected in tables, f"Expected table {expected} to exist in database"

    # Query RLS policy
    res_rls = subprocess.run(
        [
            "psql", "-h", "localhost", "-U", "postgres", "-d", "arc_test", "-t", "-c",
            "SELECT policyname FROM pg_policies WHERE tablename = 'traces';"
        ],
        capture_output=True,
        text=True,
        check=True
    )
    policies = [p.strip() for p in res_rls.stdout.splitlines() if p.strip()]
    assert "agent_isolation_policy" in policies, "Expected RLS policy 'agent_isolation_policy' on traces table"


def test_ctf_v1_invalid_outcome_status_rejected():
    """Edge Case 1: Ingest CTF payload with invalid outcome_status='halfway_done'."""
    validator = get_validator("ctf_v1.json")
    payload = {
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "agent": {"name": "refund-agent", "version": "2.14.0"},
        "model": {"provider": "anthropic", "model_id": "claude-sonnet-4-6"},
        "started_at": "2026-09-14T09:12:04.221Z",
        "determinism_level": "L2",
        "steps": [],
        "effects": [],
        "outcome": {
            "outcome_status": "halfway_done",
            "status_source": "reconciliation_webhook"
        }
    }
    with pytest.raises(jsonschema.exceptions.ValidationError) as exc_info:
        validator.validate(payload)
    assert "halfway_done" in str(exc_info.value) or "outcome" in str(exc_info.value)


def test_rejected_candidates_unique_hash_constraint():
    """Edge Case 2: Attempt inserting 2 records with identical statement_hash into rejected_candidates table."""
    # Reset table
    subprocess.run(
        ["psql", "-h", "localhost", "-U", "postgres", "-d", "arc_test", "-c", "TRUNCATE TABLE rejected_candidates;"],
        capture_output=True,
        text=True,
        check=False
    )

    stmt1 = (
        "INSERT INTO rejected_candidates (statement_hash, original_candidate_id, reason, rejected_by) "
        "VALUES ('hash_abc_123', 'cand_01', 'Duplicate invariant', 'admin');"
    )
    res1 = subprocess.run(
        ["psql", "-h", "localhost", "-U", "postgres", "-d", "arc_test", "-c", stmt1],
        capture_output=True,
        text=True,
        check=False
    )
    assert res1.returncode == 0

    stmt2 = (
        "INSERT INTO rejected_candidates (statement_hash, original_candidate_id, reason, rejected_by) "
        "VALUES ('hash_abc_123', 'cand_02', 'Another reason', 'reviewer');"
    )
    res2 = subprocess.run(
        ["psql", "-h", "localhost", "-U", "postgres", "-d", "arc_test", "-c", stmt2],
        capture_output=True,
        text=True,
        check=False
    )
    assert res2.returncode != 0, "Expected unique constraint violation on statement_hash"
    assert "duplicate key value" in res2.stderr or "unique constraint" in res2.stderr
