"""Unit tests for Approval Gateway & Rejected Candidate Dedup (TASK-P3-004).

Tests candidate rejection, normalized SHA-256 statement hash persistence,
miner auto-deduplication, catalog sync directional enforcement, and CLI reconsider command.
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.abspath("control-plane"))

from approval_gateway.gateway import ApprovalGateway
from collector.main import app as collector_app
from fastapi.testclient import TestClient
from miner.ast_miner import ASTMiner
from typer.testing import CliRunner
from warehouse.db_store import DatabaseStore

from cli.main import app as cli_app

client = TestClient(collector_app)
runner = CliRunner()


def test_reject_candidate_saves_to_rejected_table() -> None:
    """Happy Path 1: test_reject_candidate_saves_to_rejected_table.

    Calling POST /v1/mining/candidates/cand_123/reject with reason="Downstream service handles validation".
    Candidate is stored in rejected_candidates table with normalized SHA-256 statement_hash.
    """
    db_store = DatabaseStore.get_shared_instance()

    # Seed candidate statement in DB
    statement = "  Assert check: refund_amount <= order_total  "
    db_store.insert_candidate({
        "candidate_id": "cand_123",
        "statement": statement,
        "category": "conservation",
        "check": "refund_amount <= order_total",
        "status": "pending",
    })

    # Test API endpoint
    response = client.post(
        "/v1/mining/candidates/cand_123/reject",
        json={"reason": "Downstream service handles validation", "statement": statement},
    )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "rejected"
    assert res_data["candidate_id"] == "cand_123"
    assert res_data["reason"] == "Downstream service handles validation"

    # Verify statement_hash is normalized lowercase + trim SHA-256
    expected_normalized = statement.strip().lower()
    expected_hash = hashlib.sha256(expected_normalized.encode("utf-8")).hexdigest()
    assert res_data["statement_hash"] == expected_hash

    # Verify persistence in rejected_candidates table
    rejected_entry = db_store.get_rejected_candidate_by_hash(expected_hash)
    assert rejected_entry is not None
    assert rejected_entry["reason"] == "Downstream service handles validation"
    assert rejected_entry["original_candidate_id"] == "cand_123"


def test_miner_skips_rejected_statement_hash() -> None:
    """Happy Path 2: test_miner_skips_rejected_statement_hash.

    Miner proposes a new candidate whose statement when normalized matches statement_hash
    in rejected_candidates. Miner automatically skips this candidate from pending queue.
    """
    db_store = DatabaseStore.get_shared_instance()
    gateway = ApprovalGateway(db_store=db_store)

    statement = "Assert check: price >= 0"
    normalized_statement = statement.strip().lower()
    expected_hash = hashlib.sha256(normalized_statement.encode("utf-8")).hexdigest()

    # Reject statement
    gateway.reject_candidate(
        candidate_id="cand_prev_rejected",
        reason="Manually blacklisted",
        candidate_statement=statement,
    )

    assert db_store.get_rejected_candidate_by_hash(expected_hash) is not None
    assert db_store.is_statement_rejected(statement) is True

    # Run miner with db_store set
    miner = ASTMiner(db_store=db_store)
    python_code = "assert price >= 0"
    mined = miner.mine_python_source(python_code)

    # Mined candidate should be automatically filtered out/skipped
    assert len(mined) == 0
    assert len(miner.get_candidates()) == 0


def test_approval_gateway_prevents_db_to_yaml_auto_sync() -> None:
    """Edge Case 1: test_approval_gateway_prevents_db_to_yaml_auto_sync.

    Endpoint /v1/catalog/sync only reads from repo YAML into DB cache,
    rejecting any direct auto-sync write-back request from DB to YAML file without a PR commit.
    """
    # Valid forward sync (YAML to DB)
    res_valid = client.post("/v1/catalog/sync", json={"direction": "yaml_to_db"})
    assert res_valid.status_code == 200
    assert res_valid.json()["status"] == "synced"
    assert res_valid.json()["direction"] == "yaml_to_db"

    # Forbidden reverse auto-sync (DB to YAML)
    res_reverse = client.post(
        "/v1/catalog/sync",
        json={"direction": "db_to_yaml", "reverse": True},
    )
    assert res_reverse.status_code == 400
    detail = res_reverse.json()["detail"]
    assert "Direct auto-sync from DB to YAML is forbidden" in detail


def test_cli_catalog_reconsider_removes_from_rejected() -> None:
    """Edge Case 2: test_cli_catalog_reconsider_removes_from_rejected.

    Run command arc catalog reconsider --hash <hash>.
    Record is removed from rejected_candidates, allowing engineers to re-evaluate in future.
    """
    db_store = DatabaseStore.get_shared_instance()
    gateway = ApprovalGateway(db_store=db_store)

    statement = "Assert check: timeout_ms > 0"
    res = gateway.reject_candidate(
        candidate_id="cand_to_reconsider",
        reason="Temporary rejection for evaluation",
        candidate_statement=statement,
    )
    stmt_hash = res["statement_hash"]

    # Verify present in rejected table
    assert db_store.get_rejected_candidate_by_hash(stmt_hash) is not None

    # Execute CLI reconsider command
    cli_res = runner.invoke(cli_app, ["catalog", "reconsider", "--hash", stmt_hash])
    assert cli_res.exit_code == 0
    assert "Successfully removed statement hash" in cli_res.output or stmt_hash in cli_res.output

    # Verify entry is removed from database
    assert db_store.get_rejected_candidate_by_hash(stmt_hash) is None
    assert db_store.is_statement_rejected(statement) is False
