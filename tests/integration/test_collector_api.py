"""Integration tests for Control Plane Trace Warehouse & Collector REST API.

Covers:
- test_post_collector_traces_success: Valid ingestion, SHA-256 blob hashing to S3, Postgres metadata insertion.
- test_get_trace_by_id_reconstructs_ctf: Reconstruction of CTF v1.0 from Postgres + S3.
- test_get_traces_rls_isolation: RLS policy isolation per agent.
- test_post_collector_unauthorized_missing_token: 401 Unauthorized handling for missing/invalid token.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from arc.control_plane.collector.main import app, warehouse
from arc.control_plane.warehouse.blob_store import S3BlobStore
from arc.control_plane.warehouse.db_store import DatabaseStore

VALID_TOKEN = "valid_test_token_123"


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sets environment variables and resets warehouse stores for isolated testing."""
    monkeypatch.setenv("ARC_API_TOKEN_SECRET", VALID_TOKEN)

    # Re-initialize clean test warehouse instances
    db_store = DatabaseStore(":memory:")
    blob_store = S3BlobStore()
    warehouse.db = db_store
    warehouse.blob = blob_store


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def sample_ctf_payload(
    trace_id: str = "0af7651916cd43dd8448eb211c80319c", agent_name: str = "refund-agent"
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "session_id": "sess_9f21",
        "agent": {
            "name": agent_name,
            "version": "2.14.0",
            "git_sha": "a3f91c2",
        },
        "model": {
            "provider": "anthropic",
            "model_id": "claude-sonnet-4-6",
            "params": {"temperature": 0.0, "top_p": 1.0, "seed": 42},
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
                    "args": {"order_id": "ord_8842", "amount": 45.99},
                    "idempotency_key": "ord_8842:refund:1",
                    "declared_mutating": True,
                },
                "response": {
                    "status": "ok",
                    "body": {"status": "success", "transaction_id": "tx_9981"},
                    "latency_ms": 940,
                },
                "state_snapshot": {"account_balance": 1000.0},
                "forkable": True,
                "fork_reasons": ["mutating_call"],
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
                "observed_at_step": 7,
            }
        ],
        "final_state_ref": {"balance": 954.01},
        "outcome": {
            "status": "completed",
            "status_source": "reconciliation_webhook",
            "cost_usd": 0.084,
            "wall_ms": 8412,
        },
        "redaction_key_id": "rk_customer_2026_09",
    }


def test_post_collector_traces_success(client: TestClient) -> None:
    """POST /v1/collector/traces with valid payload and token stores trace and hashes blobs."""
    payload = sample_ctf_payload()
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}

    response = client.post("/v1/collector/traces", json=payload, headers=headers)
    assert response.status_code in [200, 202]
    data = response.json()
    assert data["status"] == "accepted"
    assert data["trace_id"] == payload["trace_id"]

    # Verify trace exists in database
    db_trace = warehouse.db.get_trace_by_id(payload["trace_id"])
    assert db_trace is not None
    assert db_trace["trace"]["agent_name"] == "refund-agent"

    # Verify blobs were stored with sha256 prefix
    step = db_trace["steps"][0]
    assert step["args_ref"].startswith("sha256:")
    assert step["body_ref"].startswith("sha256:")

    # Verify content in S3 blob store
    args_content = warehouse.blob.get(step["args_ref"])
    assert args_content == {"order_id": "ord_8842", "amount": 45.99}


def test_get_trace_by_id_reconstructs_ctf(client: TestClient) -> None:
    """GET /v1/traces/{trace_id} reconstructs intact CTF v1.0 merging DB metadata & S3 blobs."""
    payload = sample_ctf_payload(trace_id="0af765_recon_test")
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}

    # Ingest payload
    post_res = client.post("/v1/collector/traces", json=payload, headers=headers)
    assert post_res.status_code in [200, 202]

    # Fetch reconstructed CTF
    get_res = client.get(f"/v1/traces/{payload['trace_id']}", headers=headers)
    assert get_res.status_code == 200
    ctf = get_res.json()

    assert ctf["trace_id"] == payload["trace_id"]
    assert ctf["agent"]["name"] == "refund-agent"
    assert ctf["model"]["provider"] == "anthropic"
    assert len(ctf["steps"]) == 1
    assert ctf["steps"][0]["request"]["tool"] == "issue_refund"
    assert ctf["steps"][0]["request"]["args_ref"].startswith("sha256:")
    assert ctf["steps"][0]["response"]["body_ref"].startswith("sha256:")
    assert len(ctf["effects"]) == 1
    assert ctf["effects"][0]["effect_id"] == "eff_003"


def test_get_traces_rls_isolation(client: TestClient) -> None:
    """GET /v1/traces with RLS context only returns traces allowed for the specified agent."""
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}

    # Ingest refund-agent trace
    payload_refund = sample_ctf_payload(trace_id="trace_refund_101", agent_name="refund-agent")
    client.post("/v1/collector/traces", json=payload_refund, headers=headers)

    # Ingest billing-agent trace
    payload_billing = sample_ctf_payload(trace_id="trace_billing_202", agent_name="billing-agent")
    client.post("/v1/collector/traces", json=payload_billing, headers=headers)

    # Query with RLS allowed agents = refund-agent
    rls_headers = {
        "Authorization": f"Bearer {VALID_TOKEN}",
        "X-Allowed-Agents": "refund-agent",
    }
    res = client.get("/v1/traces", headers=rls_headers)
    assert res.status_code == 200
    traces = res.json()

    assert len(traces) == 1
    assert traces[0]["trace_id"] == "trace_refund_101"
    assert traces[0]["agent_name"] == "refund-agent"


def test_post_collector_unauthorized_missing_token(client: TestClient) -> None:
    """POST /v1/collector/traces without valid Authorization token returns HTTP 401."""
    payload = sample_ctf_payload()

    # Case 1: No Authorization header
    res1 = client.post("/v1/collector/traces", json=payload)
    assert res1.status_code == 401
    assert res1.json()["detail"] == "Not authenticated"

    # Case 2: Invalid Bearer token
    invalid_headers = {"Authorization": "Bearer invalid_token_xyz"}
    res2 = client.post("/v1/collector/traces", json=payload, headers=invalid_headers)
    assert res2.status_code == 401
    assert res2.json()["detail"] == "Not authenticated"
