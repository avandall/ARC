"""Unit tests for Cassette Engine & Rule-based Masking Matcher.

Mandatory Test Cases:
- test_cassette_player_exact_hash_match: SHA-256 canonical hash exact matching.
- test_rule_based_masking_matcher_dynamic_fields: Rule-based dynamic field masking matching.
- test_cassette_miss_transparent_abort: Unmatched tool raises CassetteMissException and updates miss rate metric.
- test_rule_based_matcher_detects_semantic_payload_change: Reject match on business payload mismatch.
"""

import os
import sys
from typing import Any

import pytest

# Ensure execution/sandbox-runner is in sys.path
sys.path.insert(0, os.path.abspath("execution/sandbox-runner"))

from cassette_player import (
    CassetteMissException,
    CassettePlayer,
    CassetteRecord,
    compute_canonical_hash,
)


def test_cassette_player_exact_hash_match() -> None:
    """Happy Path 1: Verify exact canonical SHA-256 hash match strategy."""
    args = {"order_id": 8842, "amount_cents": 4599}
    expected_response = {"status": "ok", "refund_id": "ref_8842_001"}

    record = CassetteRecord(
        tool="issue_refund",
        request_args=args,
        response=expected_response,
        status="ok",
    )

    player = CassettePlayer(records=[record])
    result = player.replay("issue_refund", args)

    assert result == expected_response
    assert result.get("status") == "ok"
    assert player.exact_matches == 1
    assert player.rule_matches == 0
    assert player.miss_count == 0
    assert player.cassette_miss_rate == 0.0


def test_rule_based_masking_matcher_dynamic_fields() -> None:
    """Happy Path 2: Verify rule-based masking matcher strips dynamic fields."""
    recorded_args = {"order_id": 8842, "amount_cents": 4599}
    recorded_response = {"status": "ok", "refund_id": "ref_8842_002"}

    record = CassetteRecord(
        tool="issue_refund",
        request_args=recorded_args,
        response=recorded_response,
        status="ok",
    )

    player = CassettePlayer(records=[record])

    # Replay request has noise dynamic fields (timestamp, request_id)
    replay_args = {
        "order_id": 8842,
        "amount_cents": 4599,
        "timestamp": "2026-09-17T14:00:00Z",
        "request_id": "req_12345",
        "nonce": "nonce_abc",
        "client_trace_id": "trace_xyz",
        "session_token": "tok_secret",
    }

    result = player.replay("issue_refund", replay_args)

    assert result == recorded_response
    assert player.rule_matches == 1
    assert player.exact_matches == 0
    assert player.miss_count == 0
    assert player.cassette_miss_rate == 0.0


def test_cassette_miss_transparent_abort() -> None:
    """Edge Case 1: Unmatched tool without model fallback raises CassetteMissException and updates miss rate metric."""
    player = CassettePlayer(records=[])

    slack_args = {"channel": "#alerts", "message": "Refund processed"}

    with pytest.raises(CassetteMissException) as exc_info:
        player.replay("send_slack_alert", slack_args)

    assert exc_info.value.tool_name == "send_slack_alert"
    assert exc_info.value.request_args == slack_args
    assert player.miss_count == 1
    assert player.total_requests == 1
    assert player.cassette_miss_rate == 1.0


def test_rule_based_matcher_detects_semantic_payload_change() -> None:
    """Edge Case 2: Business payload modification fails rule-based matching and falls through to miss flow."""
    recorded_args = {"order_id": 8842, "amount_cents": 4599}
    record = CassetteRecord(
        tool="issue_refund",
        request_args=recorded_args,
        response={"status": "ok", "refund_id": "ref_8842_003"},
    )

    player = CassettePlayer(records=[record])

    # Replay request modifies business payload (amount_cents: 9999 instead of 4599)
    modified_args = {
        "order_id": 8842,
        "amount_cents": 9999,
        "timestamp": "2026-09-17T14:00:00Z",
    }

    with pytest.raises(CassetteMissException):
        player.replay("issue_refund", modified_args)

    assert player.miss_count == 1
    assert player.exact_matches == 0
    assert player.rule_matches == 0
    assert player.cassette_miss_rate == 1.0


def test_tool_model_fallback() -> None:
    """Verify Strategy 3: Tool model simulator fallback invocation when cassette record misses."""
    player = CassettePlayer()

    def dummy_tool_model(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"status": "simulated", "echo_order": args.get("order_id")}

    player.register_tool_model("get_order_status", dummy_tool_model)

    res = player.replay("get_order_status", {"order_id": 999})
    assert res == {"status": "simulated", "echo_order": 999}
    assert player.tool_model_fallback_matches == 1
    assert player.miss_count == 0
    assert player.cassette_miss_rate == 0.0


def test_cassette_miss_rate_calculation() -> None:
    """Verify miss rate calculation over a sequence of hit and miss requests."""
    record = CassetteRecord(
        tool="check_stock",
        request_args={"item_id": "item_1"},
        response={"status": "ok", "in_stock": True},
    )
    player = CassettePlayer(records=[record])

    # 1st call: exact match (Hit)
    player.replay("check_stock", {"item_id": "item_1"})
    assert player.cassette_miss_rate == 0.0

    # 2nd call: missing tool (Miss)
    with pytest.raises(CassetteMissException):
        player.replay("unknown_tool", {})

    assert player.total_requests == 2
    assert player.miss_count == 1
    assert player.cassette_miss_rate == 0.5


def test_dict_record_initialization() -> None:
    """Verify initialization and add_record using dictionary format from HarnessBundle."""
    dict_record = {
        "tool": "lookup_user",
        "request_hash": f"sha256:{compute_canonical_hash({'user_id': 42})}",
        "request_args": {"user_id": 42},
        "response": {"status": "ok", "name": "Alice"},
    }

    player = CassettePlayer(records=[dict_record])
    res = player.replay("lookup_user", {"user_id": 42})
    assert res == {"status": "ok", "name": "Alice"}
    assert player.exact_matches == 1
