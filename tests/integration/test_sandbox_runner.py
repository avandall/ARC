"""Integration tests for Isolated Sandbox Runner & Passive Effect Ledger.

Mandatory Test Cases per TASK-P1-003:
- test_sandbox_runner_docker_internal_network_mode
- test_passive_effect_ledger_records_mutating_calls
- test_sandbox_egress_deny_blocks_external_internet
- test_sandbox_hard_fail_on_production_token
"""

import pytest

from arc.execution.sandbox_runner.runner import SandboxConfig, SandboxRunner
from arc.execution.sandbox_runner.security import (
    InvalidSignatureError,
    SecurityViolationError,
    compute_hmac_signature,
)


def test_sandbox_runner_docker_internal_network_mode() -> None:
    """Happy Path 1: Container initialized on arc-isolated-net (internal: true) connects to proxy."""
    config = SandboxConfig(
        network_mode="arc-isolated-net",
        internal_network=True,
        proxy_url="http://arc-proxy:8089",
    )
    runner = SandboxRunner(config=config)
    container = runner.start_container()

    assert container.is_running is True
    assert container.config.network_config.internal is True

    # Connect to mock proxy
    res = container.execute_request("http://arc-proxy:8089")
    assert res["status"] == "connected"
    assert res["proxy"] == "http://arc-proxy:8089"


def test_passive_effect_ledger_records_mutating_calls() -> None:
    """Happy Path 2: Interceptor traps mutating tool call, returns mock OK, records delta in ledger."""
    runner = SandboxRunner()
    container = runner.start_container()

    # Agent calls mutating tool issue_refund
    res = container.execute_tool("issue_refund", {"order_id": "8842", "amount": 4599})

    assert res["status"] == "ok"
    assert res["recorded"] is True

    # Check Passive Effect Ledger records
    effects = runner.ledger.get_effects()
    assert len(effects) == 1
    effect = effects[0]

    assert effect["type"] == "issue_refund"
    assert effect["resource"] == "order:8842"
    assert effect["delta"] == {"order_id": "8842", "amount": 4599}
    assert effect["step_id"] == 1
    assert "effect_id" in effect


def test_sandbox_egress_deny_blocks_external_internet() -> None:
    """Edge Case 1: Outbound requests to external domains/IPs are blocked at network bridge level."""
    runner = SandboxRunner(config=SandboxConfig(network_mode="arc-isolated-net", internal_network=True))
    container = runner.start_container()

    # Request to external domain (https://api.stripe.com) raises Egress Denied timeout
    with pytest.raises((TimeoutError, ConnectionError)) as exc_info:
        container.execute_request("https://api.stripe.com")
    assert "Egress Denied" in str(exc_info.value)

    # Request to public IP (http://8.8.8.8) raises Egress Denied timeout
    with pytest.raises((TimeoutError, ConnectionError)) as exc_info:
        container.execute_request("http://8.8.8.8")
    assert "Egress Denied" in str(exc_info.value)


def test_sandbox_hard_fail_on_production_token() -> None:
    """Edge Case 2: Environment containing production credentials immediately hard fails with SecurityViolationError."""
    runner = SandboxRunner()
    prod_env = {"STRIPE_KEY": "sk_live_999888777666555444"}

    with pytest.raises(SecurityViolationError) as exc_info:
        runner.start_container(env=prod_env)

    assert "Stripe Secret Key" in str(exc_info.value) or "sk_live_" in str(exc_info.value)


def test_sandbox_bundle_hmac_signature_verification() -> None:
    """Verify bundle HMAC signature validation rejects invalid signatures."""
    runner = SandboxRunner()
    bundle = {"task_id": "TASK-P1-003", "payload": "test_data"}
    secret = "my_bundle_secret_123"

    # Valid signature succeeds
    valid_sig = compute_hmac_signature(bundle, secret)
    container = runner.start_container(bundle_data=bundle, signature=valid_sig, secret=secret)
    assert container.is_running is True

    # Invalid signature raises InvalidSignatureError
    with pytest.raises(InvalidSignatureError):
        runner.start_container(bundle_data=bundle, signature="invalid_hmac_hash", secret=secret)
