# ARC

**[ARC](https://github.com/avandall/ARC) is an autonomous reliability & chaos engineering harness for AI agents.** Auto-mine safety invariants, simulate real-world failure modes (timeouts, 429s, race conditions), and mathematically verify safety rules before code ships.

<p align="left">
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.14-blue.svg?style=flat-square" alt="Python Versions" />
  <img src="https://img.shields.io/badge/tests-177%20passed-brightgreen.svg?style=flat-square" alt="Tests Status" />
  <img src="https://img.shields.io/badge/license-Apache--2.0-green.svg?style=flat-square" alt="License: Apache-2.0" />
</p>

```python
# agent.py
from arc import trace_agent, trace_tool

@trace_tool(name="stripe_charge")
def process_refund(order_id: str, amount: float) -> dict:
    return {"status": "ok", "refund_id": "ref_1042"}

@trace_agent(name="refund_agent")
def handle_customer_request(order_id: str) -> dict:
    return process_refund(order_id, 45.99)
```

Wrap agent functions and tools with ARC decorators. Traces and side-effects are captured with zero overhead and automatic Tier-1 secret redaction. Replay them in a zero-production sandbox to verify safety invariants (e.g. *never refund twice*).

## Quick start

### 1. Local Testing & Interactive Studio

```bash
pip install arc-reliability
arc
```

Launches the interactive terminal hub for zero-config onboarding, AST tracing auto-attach, chaos fault injection, and invariant reviews.

### 2. CI/CD Reliability Gate

```bash
arc gate --profile smoke
```

Runs end-to-end chaos verification across $K$-parallel simulation branches with 95% Wilson Score Confidence Intervals (Exit `0` = PASS, Exit `1` = FAIL).

### 3. Production Deployment

Traces run in-process with OpenTelemetry spans. Choose how you persist trace artifacts:

```bash
# Option A: Save traces to a local folder or mounted volume (no extra service needed)
export ARC_TRACE_DIR=/var/log/arc_traces

# Option B: Stream to centralized ARC Collector API
export ARC_COLLECTOR_URL=https://arc-collector.internal.net
```

When an incident occurs on production, reproduce it locally with step-by-step diagnostics:

```bash
arc repro .arc/incidents/inc_double_refund.yaml --visual
```

## CLI Reference

| Command | Description |
| :--- | :--- |
| `arc` | Launch interactive studio with smart state detection |
| `arc gate --profile smoke` | Run CI reliability gate (Exit 0 = PASS, Exit 1 = FAIL) |
| `arc repro <file> --visual` | Playwright-style terminal UI diagnostic trace |
| `arc minimize <file>` | Delta-debugging (`ddmin`) to isolate minimal fault sequence |
| `arc debug --port 8089` | Local replay debugger proxy |
| `arc catalog review` | Review candidate invariants mined from code and schemas |

## License

[Apache-2.0](LICENSE)
