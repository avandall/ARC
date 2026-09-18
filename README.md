# ARC — Autonomous Reliability & Chaos Harness for AI Agents

[![PyPI version](https://img.shields.io/pypi/v/arc-reliability.svg)](https://pypi.org/project/arc-reliability/)
[![Python versions](https://img.shields.io/pypi/pyversions/arc-reliability.svg)](https://pypi.org/project/arc-reliability/)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://img.shields.io/badge/tests-90%20passed-brightgreen.svg)]()

**ARC** (*Agent Reliability & Conformance Harness*) is a deterministic simulation and chaos-engineering test harness for production AI Agents that perform real-world side effects (calling APIs, executing DB transactions, issuing payments, modifying cloud infrastructure).

---

## 🚀 Key Capabilities

- **Zero-Prod Simulation & Fork-Replay**: Replay production agent execution traces with deterministic virtual clocks and sandboxed tool models without touching production databases.
- **Chaos Fault Injection**: Inject systematic network timeouts, rate limits, schema mismatches, and double-action faults into agent decision loops.
- **Automated Invariant Mining**: Extract safety, authorization, and financial invariants from SQL DDL schemas, OpenAPI specs, and incident postmortems with human-in-the-loop approval.
- **Delta-Debugging (`ddmin`)**: Automatically minimize long, noisy agent failure traces into the smallest reproducible YAML bug reproducer.
- **CI/CD Quality Gate**: Enforce statistical reliability verdicts in GitHub Actions or GitLab CI with standard POSIX exit codes (`arc gate`).

---

## 📦 Installation

```bash
pip install arc-reliability
```

For development and testing:
```bash
pip install "arc-reliability[dev]"
```

---

## ⚡ Quick Start

### 1. Instrument Your AI Agent with ARC SDK

```python
from arc.sdk import trace_agent, trace_tool

@trace_tool(name="payment_gateway")
def process_refund(order_id: str, amount: float) -> dict:
    # Real API call or simulated response
    return {"status": "ok", "refund_id": "ref_123"}

@trace_agent(name="refund_agent")
def handle_customer_request(order_id: str) -> dict:
    return process_refund(order_id, 45.99)

if __name__ == "__main__":
    result = handle_customer_request("8842")
    print("Agent Execution Completed:", result)
```

### 2. Run ARC CLI Commands

ARC provides a unified command-line tool `arc` for debugging, verification, and invariant catalog management:

```bash
# Evaluate trace compliance in CI pipeline
arc gate --trace trace.json --budget 100 --alpha 0.05

# Replay and verify minimal bug reproducer in local sandbox
arc repro arc-repro-8842.yaml

# Start local replay debugger proxy
arc debug --port 8080

# Review proposed invariant candidates
arc catalog review --id INV-PAY-002 --accept

# Track and tag escaped incidents
arc incidents tag INC-1042 --candidate-id INV-PAY-002
```

---

## 🏗️ Architecture

```
ARC
├── src/arc/
│   ├── sdk/                 # Interceptor, Virtual Clock, Tier-1 PII Redactor
│   ├── cli/                 # Unified CLI application (`arc`)
│   ├── execution/           # Fork Engine, Chaos Injector, Sandbox Runner
│   └── control_plane/       # Approval Gateway, Trace Warehouse, Invariant Miner
└── schemas/                 # JSON Schema & SQL DDL definitions
```

---

## 🧪 Running Tests

```bash
# Run the complete test suite (Unit, Integration, E2E)
pytest tests/

# Run static quality & security verification
python3 pipeline/scripts/verify.py
```

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).
