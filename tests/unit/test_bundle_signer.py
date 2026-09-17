"""Unit tests for HarnessBundle Generator and HMAC Signer.

Mandatory Test Cases:
- test_generate_bundle_and_verify_hmac_signature: Verify generation and HMAC signature with key 'super-secret-hmac-key'.
- test_bundle_schema_conformance: Validate bundle output against JSON schema schemas/json/bundle_v1.json.
- test_bundle_truncates_large_trace_window: Trace with 15,000 steps truncated to <= 10,000 steps (±50 window around fork point).
- test_verify_tampered_bundle_fails: Modifying 1 byte in steps payload causes signature verification failure and raises InvalidBundleSignatureError.
"""

import json
import os
import pathlib
import sys
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# Ensure control-plane is in sys.path
sys.path.insert(0, os.path.abspath("control-plane"))

from warehouse.bundle_generator import (
    BundleSignatureVerifier,
    HarnessBundleGenerator,
    InvalidBundleSignatureError,
)


def get_bundle_validator() -> Draft202012Validator:
    schema_dir = pathlib.Path("schemas/json")
    registry = Registry()
    for p in schema_dir.glob("*.json"):
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
            resource = Resource.from_contents(s)
            registry = registry.with_resource(p.name, resource)
            if "$id" in s:
                registry = registry.with_resource(s["$id"], resource)

    with open(schema_dir / "bundle_v1.json", encoding="utf-8") as f:
        target_schema = json.load(f)

    return Draft202012Validator(target_schema, registry=registry)


def sample_ctf_trace(trace_id: str = "trace_sample_001") -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "session_id": "sess_001",
        "agent": {
            "name": "refund-agent",
            "version": "1.0.0",
            "git_sha": "abc1234",
        },
        "model": {
            "provider": "anthropic",
            "model_id": "claude-sonnet-4-6",
            "params": {"temperature": 0.0, "seed": 42},
        },
        "started_at": "2026-09-17T12:00:00Z",
        "determinism_level": "L2",
        "steps": [
            {
                "step_id": 1,
                "kind": "model_decision",
                "t_virtual_ms": 100,
                "parent_step": None,
                "request": None,
                "response": None,
                "state_snapshot_ref": None,
                "forkable": False,
                "fork_reasons": [],
            },
            {
                "step_id": 2,
                "kind": "tool_call",
                "t_virtual_ms": 500,
                "parent_step": 1,
                "request": {
                    "tool": "issue_refund",
                    "args_ref": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "idempotency_key": "idem_001",
                    "declared_mutating": True,
                },
                "response": {
                    "status": "ok",
                    "body_ref": "sha256:ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                    "latency_ms": 120,
                },
                "state_snapshot_ref": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
                "forkable": True,
                "fork_reasons": ["mutating_call"],
            },
        ],
        "effects": [
            {
                "effect_id": "eff_001",
                "step_id": 2,
                "type": "financial.refund",
                "resource": "order:8842",
                "delta": {"amount_cents": -4599},
                "reversible": False,
                "idempotency_key": "idem_001",
                "observed_at_step": 2,
            }
        ],
        "final_state_ref": {"balance": 954.01},
        "outcome": {
            "status": "completed",
            "status_source": "agent_self_report",
            "cost_usd": 0.05,
            "wall_ms": 600,
        },
    }


def test_generate_bundle_and_verify_hmac_signature() -> None:
    """Happy Path 1: Generator creates HarnessBundle with HMAC-SHA256 signature, verifiable with secret key."""
    ctf = sample_ctf_trace("trace_hmac_test_001")
    secret_key = "super-secret-hmac-key"

    bundle = HarnessBundleGenerator.generate(ctf, secret_key=secret_key)

    assert "signature" in bundle
    assert bundle["signature"]["alg"] == "HMAC-SHA256"
    assert isinstance(bundle["signature"]["value"], str)
    assert len(bundle["signature"]["value"]) == 64  # SHA256 hex digest length

    # Verify signature successfully
    is_valid = BundleSignatureVerifier.verify(bundle, secret_key=secret_key)
    assert is_valid is True


def test_bundle_schema_conformance() -> None:
    """Happy Path 2: Validate bundle output against JSON schema schemas/json/bundle_v1.json."""
    ctf = sample_ctf_trace("trace_schema_test_002")
    secret_key = "super-secret-hmac-key"

    bundle = HarnessBundleGenerator.generate(ctf, secret_key=secret_key)

    assert bundle["bundle_schema_version"] == "1.0"
    assert "entrypoint" in bundle
    assert "steps" in bundle
    assert "cassettes" in bundle
    assert "effects" in bundle
    assert "signature" in bundle

    validator = get_bundle_validator()
    validator.validate(bundle)


def test_bundle_truncates_large_trace_window() -> None:
    """Edge Case 1: Trace with 15,000 steps around fork point is truncated to <= 10,000 steps."""
    total_steps = 15000
    fork_step_id = 7500

    steps = []
    for i in range(1, total_steps + 1):
        is_fork = i == fork_step_id
        steps.append(
            {
                "step_id": i,
                "kind": "tool_call" if is_fork else "model_decision",
                "t_virtual_ms": i * 10,
                "parent_step": i - 1 if i > 1 else None,
                "request": {
                    "tool": "issue_refund" if is_fork else "read_logs",
                    "args_ref": "sha256:dummy",
                    "idempotency_key": None,
                    "declared_mutating": is_fork,
                }
                if is_fork
                else None,
                "response": None,
                "state_snapshot_ref": None,
                "forkable": is_fork,
                "fork_reasons": ["mutating_call"] if is_fork else [],
            }
        )

    large_ctf = sample_ctf_trace("trace_large_15k")
    large_ctf["steps"] = steps

    bundle = HarnessBundleGenerator.generate(large_ctf, secret_key="super-secret-hmac-key")

    assert len(bundle["steps"]) <= 10000
    # Specifically, window around fork point (±50 steps) yields 101 steps
    assert len(bundle["steps"]) == 101

    # Verify schema conformance of truncated bundle
    validator = get_bundle_validator()
    validator.validate(bundle)


def test_verify_tampered_bundle_fails() -> None:
    """Edge Case 2: Modifying 1 byte in payload steps causes verification failure and raises InvalidBundleSignatureError."""
    ctf = sample_ctf_trace("trace_tamper_test_004")
    secret_key = "super-secret-hmac-key"

    bundle = HarnessBundleGenerator.generate(ctf, secret_key=secret_key)

    # Verify pristine bundle first
    assert BundleSignatureVerifier.verify(bundle, secret_key, raise_on_error=False) is True

    # Tamper 1 byte in payload steps
    bundle["steps"][0]["t_virtual_ms"] += 1

    # Verification with raise_on_error=False returns False
    assert BundleSignatureVerifier.verify(bundle, secret_key, raise_on_error=False) is False

    # Verification with default raise_on_error=True raises InvalidBundleSignatureError
    with pytest.raises(InvalidBundleSignatureError) as exc_info:
        BundleSignatureVerifier.verify(bundle, secret_key)

    assert "tampered" in str(exc_info.value) or "Invalid bundle signature" in str(exc_info.value)
