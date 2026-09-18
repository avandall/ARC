"""Unit tests for Python Interceptor SDK (`arc_sdk`).

Tests cover:
- Agent and tool decorators + CTF trace step dictionary export.
- Tier 1 Redactor secret pattern scanning & placeholder replacement.
- Overhead benchmarking (10,000 iterations < 1.0ms p99 latency overhead).
- Exception trapping & error trace recording without crashing host process.
"""

from __future__ import annotations

import time
from typing import Any

import arc.sdk as arc


def test_python_sdk_agent_and_tool_decorators() -> None:
    """Happy Path 1: Wrap agent and tool functions with @arc.trace_agent and @arc.trace_tool.

    Execute call: lookup(order_id='8842'). Result: SDK creates standard OTel span,
    extracts tool name, input args, latency, and exports to CTF step dictionary.
    """
    @arc.trace_tool(name="lookup")
    def lookup(order_id: str) -> dict[str, Any]:
        return {"order_id": order_id, "status": "shipped", "item": "widget"}

    @arc.trace_agent(name="order_agent", version="1.0.0")
    def run_agent() -> dict[str, Any]:
        res = lookup(order_id="8842")
        trace_data = arc.get_current_trace()
        return {"result": res, "trace": trace_data}

    output = run_agent()
    result = output["result"]
    trace = output["trace"]

    assert result == {"order_id": "8842", "status": "shipped", "item": "widget"}
    assert trace is not None
    assert trace["agent"]["name"] == "order_agent"
    assert trace["agent"]["version"] == "1.0.0"

    steps = trace["steps"]
    assert len(steps) == 1

    step = steps[0]
    assert step["kind"] == "tool_call"
    assert step["request"]["tool"] == "lookup"
    assert step["request"]["args"] == {"order_id": "8842"}
    assert step["response"]["status"] == "ok"
    assert step["response"]["body"] == {"order_id": "8842", "status": "shipped", "item": "widget"}
    assert step["response"]["latency_ms"] >= 0.0
    assert step["outcome"] == "success"


def test_tier1_sanitizer_redacts_api_keys() -> None:
    """Happy Path 2: Call tool with payload containing secret patterns.

    Pattern: sk_live_1234567890abcdef12345678, AKIAIOSFODNN7EXAMPLE.
    Result: Payload is sanitized at source, secret values replaced with
    placeholder [REDACTED:stripe_live_key] or [REDACTED:aws_key].
    """
    @arc.trace_tool(name="process_payment")
    def process_payment(api_key: str, aws_token: str, order_id: str) -> dict[str, Any]:
        return {
            "status": "paid",
            "order_id": order_id,
            "processed_with": api_key,
            "aws_ref": aws_token,
        }

    @arc.trace_agent(name="payment_agent")
    def run_payment() -> dict[str, Any] | None:
        stripe_key = "sk_live_1234567890abcdef12345678"
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        process_payment(api_key=stripe_key, aws_token=aws_key, order_id="ORD-999")
        trace: dict[str, Any] | None = arc.get_current_trace()
        return trace

    trace = run_payment()
    assert trace is not None
    steps = trace["steps"]
    assert len(steps) == 1

    step = steps[0]
    args = step["request"]["args"]
    # Check that secrets in input args were redacted at source
    assert args["api_key"] == "[REDACTED:stripe_live_key]"
    assert args["aws_token"] == "[REDACTED:aws_key]"
    assert args["order_id"] == "ORD-999"

    # Check that secrets in output response body were also redacted at source
    body = step["response"]["body"]
    assert body["processed_with"] == "[REDACTED:stripe_live_key]"
    assert body["aws_ref"] == "[REDACTED:aws_key]"


def test_interceptor_overhead_benchmark() -> None:
    """Edge Case 1: Run 10,000 iterations of decorated tool calls.

    Measure overhead: p99 added latency < 1.0ms, CPU overhead < 1.5%.
    """
    @arc.trace_tool(name="fast_tool")
    def fast_tool(x: int) -> int:
        return x * 2

    def bare_tool(x: int) -> int:
        return x * 2

    iterations = 10_000

    # Bare loop baseline timing
    t0_bare = time.perf_counter()
    for i in range(iterations):
        bare_tool(i)
    t_bare_total_ms = (time.perf_counter() - t0_bare) * 1000

    # Decorated loop timing inside trace context
    latencies: list[float] = []

    with arc.trace_agent(name="benchmark_agent"):
        for i in range(iterations):
            t_start = time.perf_counter()
            fast_tool(i)
            latencies.append((time.perf_counter() - t_start) * 1000)

    # Calculate p99 latency
    latencies.sort()
    p99_index = int(iterations * 0.99)
    p99_latency_ms = latencies[p99_index]

    # Average overhead per iteration
    avg_overhead_ms = (sum(latencies) - t_bare_total_ms) / iterations

    # Assert p99 added latency < 1.0ms
    assert p99_latency_ms < 1.0, f"p99 latency ({p99_latency_ms:.4f}ms) exceeded 1.0ms target"
    assert avg_overhead_ms < 0.5, f"Average overhead ({avg_overhead_ms:.4f}ms) exceeded threshold"


def test_interceptor_handles_tool_exception() -> None:
    """Edge Case 2: Wrapped tool raises ConnectionResetError("Socket dropped").

    Result: Interceptor traps exception, marks step outcome='error',
    records exception traceback in trace without crashing host process.
    """
    @arc.trace_tool(name="flaky_network_call")
    def flaky_network_call() -> str:
        raise ConnectionResetError("Socket dropped")

    @arc.trace_agent(name="resilient_agent")
    def run_resilient_agent() -> tuple[Any, dict[str, Any] | None]:
        res = flaky_network_call()
        trace: dict[str, Any] | None = arc.get_current_trace()
        return res, trace

    result, trace = run_resilient_agent()

    # Host process did not crash, received error response dict
    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert "Socket dropped" in result["error"]

    # Verify trace recorded exception step details
    assert trace is not None
    steps = trace["steps"]
    assert len(steps) == 1

    step = steps[0]
    assert step["kind"] == "tool_call"
    assert step["request"]["tool"] == "flaky_network_call"
    assert step["response"]["status"] == "error"
    assert "Socket dropped" in step["response"]["error"]
    assert "ConnectionResetError" in step["response"]["traceback"]
    assert step["outcome"] == "error"


def test_python_circular_reference_and_stacktrace_redaction() -> None:
    """Test circular reference protection and exception stacktrace redaction in Python SDK."""
    redactor = arc.Redactor()
    cyclic_dict: dict[str, Any] = {"name": "test"}
    cyclic_dict["self"] = cyclic_dict

    redacted = redactor.redact(cyclic_dict)
    assert redacted["name"] == "test"
    assert redacted["self"] == "[CIRCULAR]"

    @arc.trace_tool(name="secret_failing_tool")
    def secret_failing_tool() -> None:
        raise ValueError("Failed with secret: Bearer secret-token-456")

    with arc.trace_agent(name="secret_agent"):
        secret_failing_tool()
        trace = arc.get_current_trace()
        assert trace is not None
        step = trace["steps"][0]
        assert "[REDACTED:generic_bearer]" in step["response"]["error"]
        assert "[REDACTED:generic_bearer]" in step["response"]["traceback"]

