# ARC — Agent Reliability & Chaos Harness

**Deterministic simulation and chaos engineering harness for production AI agents.**

[![PyPI version](https://img.shields.io/pypi/v/arc-reliability.svg)](https://pypi.org/project/arc-reliability/)
[![Python versions](https://img.shields.io/pypi/pyversions/arc-reliability.svg)](https://pypi.org/project/arc-reliability/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()

---

## What is ARC?

When production AI agents interact with real-world systems (APIs, databases, payment gateways), transient failures (timeouts, 429 rate limits, bad schemas) often cause silent disaster:
- The agent retries without an idempotency key and **charges a customer twice**.
- An unhandled error causes the agent to **corrupt database state**.
- Flaky external tools lead to **non-reproducible bugs**.

**ARC** gives you a **zero-production sandbox** to replay agent execution traces, inject systematic chaos faults, and mathematically verify safety rules before deploying to production.

---

## How It Works

1. **Record**: Capture agent runs into Canonical Trace Format (CTF v1.0) with `@trace_agent` and `@trace_tool`.
2. **Replay & Fault Injection**: Replay traces against simulated tool models with virtual clocks, injecting timeouts, rate limits, or concurrent mutations.
3. **Verify**: Check safety invariants (e.g., *never refund more than order total*) deterministically and enforce pass/fail quality gates in CI/CD.

```
Agent Trace  ──►  Replay Sandbox (Zero-Prod)  ──►  Fault Injection  ──►  Safety Invariant Check
                        │                                                      │
                  Virtual Clock                                          Pass / Block CI
```

---

## Installation

```bash
pip install arc-reliability
```

---

## Quickstart

### 1. Instrument Your Agent

Wrap your agent and tools with ARC decorators. Traces and state transitions are captured automatically:

```python
from arc import trace_agent, trace_tool

@trace_tool(name="payment_gateway")
def process_refund(order_id: str, amount: float) -> dict:
    return {"status": "ok", "refund_id": "ref_1042", "amount": amount}

@trace_agent(name="refund_agent")
def handle_customer_request(order_id: str) -> dict:
    return process_refund(order_id, 45.99)

if __name__ == "__main__":
    result = handle_customer_request("ORD-8842")
    print(result)
```

### 2. Replay with Fault Injection & Verify Invariants

Test how your agent handles a network timeout after a commit without touching your live database:

```python
from arc.execution.fork_engine import FaultCatalog, FaultSpec, FaultType
from arc.execution.sandbox_runner import SandboxRunner

# 1. Define chaos fault: timeout occurs AFTER payment commits
catalog = FaultCatalog()
catalog.add_fault(FaultSpec(
    at_step=1,
    fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
    target_tool="payment_gateway"
))

# 2. Define safety invariant: payment must never be executed twice
invariant = {
    "id": "INV-NO-DOUBLE-CHARGE",
    "statement": "Payment tool must not be called more than once",
    "category": "safety",
    "check": "len([e for e in effects if e.type == 'payment_gateway']) <= 1",
    "severity": "critical"
}

# 3. Run in zero-prod sandbox
runner = SandboxRunner()
verdict = runner.run_with_faults(fault_spec=catalog, target_invariant=invariant)

print("Passed:", verdict["passed"])  # False if double-charge occurred
```

---

## CLI at a Glance

ARC provides a single command-line interface for CI/CD gates and debugging:

```bash
# Evaluate trace reliability in CI pipeline (exit code 0 = pass, 1 = fail)
arc gate --trace trace.json --profile smoke

# Replay and diagnose a bug reproducer artifact
arc repro arc-repro-8842.yaml

# Minimize a complex failure trace into the smallest reproducible bug
arc minimize arc-repro-long.yaml -o arc-repro-min.yaml

# Start local replay debugger proxy
arc debug --port 8089

# Review candidate invariants mined from code and schemas
arc catalog review --id INV-PAY-002 --accept
```

---

## Core Capabilities

- **Zero-Prod Replay**: Mock and replay agent side-effects in memory with `PassiveEffectLedger`.
- **Chaos Fault Catalog**: Test against 14+ faults: `timeout_before_commit`, `timeout_after_commit`, `http_429`, `bad_schema`, `duplicate_action`, `concurrent_write`.
- **Restricted AST Invariant Engine**: Write safety checks with safe Python expressions. Unsafe I/O and non-deterministic calls (`random()`, `time.now()`) are strictly blocked.
- **Delta-Debugging (`ddmin`)**: Automatically isolates the exact fault that caused an invariant violation.
- **Statistical CI Gate**: Validates reliability across parallel execution branches using 95% Wilson Score Confidence Intervals.
- **Tier-1 PII Redaction**: Scrubs API keys (AWS, Stripe, Bearer tokens, JWTs) and high-entropy secrets at the source.

---

## Documentation

For full API references, function signatures, and architecture details, see [API Documentation](docs/API_DOCUMENTATION.md).

---

## License

[Apache License 2.0](LICENSE)
