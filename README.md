<p align="center">
  <pre align="center">
  █████╗ ██████╗  ██████╗ 
 ██╔══██╗██╔══██╗██╔════╝ 
 ███████║██████╔╝██║      
 ██╔══██║██╔══██╗██║      
 ██║  ██║██║  ██║╚██████╗ 
 ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ 
  </pre>
  <h3 align="center">ARC — Autonomous Reliability & Chaos Harness for AI Agents</h3>
  <p align="center">
    <strong>Deterministic simulation, invariant auto-mining, and chaos engineering for production agent workflows.</strong>
  </p>
</p>

<p align="center">
  <a href="#quickstart"><strong>Quickstart</strong></a> |
  <a href="#how-it-works"><strong>How It Works</strong></a> |
  <a href="#interactive-cli--chaos-hub"><strong>Interactive CLI</strong></a> |
  <a href="#safety-invariants"><strong>Safety Invariants</strong></a> |
  <a href="#chaos-fault-catalog"><strong>Chaos Catalog</strong></a> |
  <a href="#cli-reference"><strong>CLI Reference</strong></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/arc-reliability/"><img src="https://img.shields.io/badge/pypi-v0.1.0-blue.svg?style=flat-square" alt="PyPI version" /></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.14-blue.svg?style=flat-square" alt="Python Versions" />
  <img src="https://img.shields.io/badge/tests-176%20passed-brightgreen.svg?style=flat-square" alt="Tests Status" />
  <img src="https://img.shields.io/badge/license-Apache--2.0-green.svg?style=flat-square" alt="License: Apache-2.0" />
  <img src="https://img.shields.io/badge/code%20style-ruff%20%7C%20black-000000.svg?style=flat-square" alt="Code Style" />
</p>

---

## Agents that fail safely before hitting production.

When production AI agents interact with real-world infrastructure (databases, payment APIs, microservices), transient real-world glitches cause silent catastrophes:
- A payment API times out *after* charging the card; the agent retries without idempotency and **charges the customer twice**.
- A database connection drops mid-flow; the agent hallucinates an error recovery path and **corrupts ledger state**.
- Rate-limit (HTTP 429) spikes trigger retry storms that **exhaust token and API quotas**.

**ARC** provides a **zero-production deterministic sandbox** to replay agent execution traces, auto-mine safety invariants directly from code and database schemas, inject systematic chaos faults, and mathematically verify behavior before deployment.

---

## How It Works

```
 ┌────────────────┐       ┌──────────────────────┐       ┌─────────────────────┐
 │  Agent Trace   │  ──►  │ Zero-Prod Sandbox    │  ──►  │ Chaos Fault Engine  │
 │ (@trace_agent) │       │ (Virtual Clock / DB) │       │ (Timeout, 429, DB)  │
 └────────────────┘       └──────────────────────┘       └─────────────────────┘
                                                                    │
                                                                    ▼
 ┌────────────────┐       ┌──────────────────────┐       ┌─────────────────────┐
 │  Block CI / CD │  ◄──  │ Playwright Reproduce │  ◄──  │ Invariant Evaluator │
 │ (Wilson Score) │       │ (Delta-Debugging)    │       │ (No Double Charge)  │
 └────────────────┘       └──────────────────────┘       └─────────────────────┘
```

1. **Record**: Capture agent actions, tool calls, and state transitions into Canonical Trace Format (CTF v1.0).
2. **Replay & Fault Injection**: Run traces inside a sandboxed environment with virtual clocks and tool models, injecting network timeouts, deadlocks, and schema corruptions.
3. **Verify**: Evaluate AST-restricted safety invariants (e.g. *refunds cannot exceed charge amount*) with 95% Wilson Score Confidence Intervals.

---

## Quickstart

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/avandall/ARC.git
cd ARC

# Install in development mode with uv or pip
uv pip install -e .
```

### 2. Launch the Interactive Studio

Run `arc` in your terminal for zero-config onboarding and the interactive chaos testing studio:

```bash
arc
```

- **Smart State Detection**: On your first run, ARC automatically discovers your project root, generates `.arc/config.yaml`, creates `.env.example`, and configures credentials.
- **AST Instrumentation Scanner**: Interactively scans your agent code to auto-attach `@trace_agent` and `@trace_tool` with git diff previews.
- **Continuous Session Hub**: Stay in the CLI loop to inject faults, review mined invariants, or reproduce incidents without restarting.

### 3. Instrument Your Agent

Wrap your agent functions and tools with ARC decorators. Traces, tool arguments, and execution order are captured without affecting runtime behavior:

```python
from arc import trace_agent, trace_tool

@trace_tool(name="stripe_charge")
def process_payment(customer_id: str, amount_cents: int, idempotency_key: str) -> dict:
    # Real payment call in production; mocked safely during ARC chaos replay
    return {"status": "succeeded", "charge_id": "ch_3M4x9", "amount": amount_cents}

@trace_agent(name="billing_agent")
def handle_refund_or_charge(customer_id: str, amount_cents: int) -> dict:
    key = f"charge_{customer_id}_{amount_cents}"
    return process_payment(customer_id, amount_cents, idempotency_key=key)

if __name__ == "__main__":
    handle_refund_or_charge("cus_9912", 5000)
```

---

## Interactive CLI & Chaos Hub

ARC provides an interactive terminal hub for day-to-day development and debugging:

```
╭───────────────── ARC Autonomous Reliability & Chaos Engine ──────────────────╮
│ Project: /workspace/ARC  |  Config: .arc/config.yaml [Active]                │
╰──────────────────────────────────────────────────────────────────────────────╯
? Select an action:
  [1] Setup & Instrumentation (Configure / Attach Tracing)
  [2] Fault Injection & Chaos Testing (Security Check / Gate)
  [3] Auto-Mine Invariants (Extract rules from Code / Schema / Postmortems)
  [4] Exit
```

### Submenu Actions:
- **[1.1] Edit Configuration**: Switch active LLM providers (Anthropic, OpenAI, Local Ollama), configure fork parallelism ($K$), and manage API key fallbacks.
- **[1.2] Setup Tracing**: Interactive AST scanner that reviews code diffs and attaches tracing decorators automatically.
- **[2.1] Full Flow Chaos Gate**: Execute end-to-end chaos verification across smoke ($K=3$) and full ($K=20$) catalog profiles.
- **[2.2] Mock DB & Third-Party Simulation**: Inject realistic upstream faults (`db_down`, `payment_timeout`, `rate_limit`) into live agent branches.
- **[2.3] K-Parallel Fork Replay**: Run multiple concurrent simulation branches to catch non-deterministic race conditions and state leakage.
- **[2.4] Reproduce Bug from Prod Incidents**: Load production `.arc/incidents/` YAML dumps and generate step-by-step Playwright-style visual traces.
- **[3] Auto-Mine Invariants**: AST mining engine scans database DDL schemas, `raise Exception` guards, and docstrings to generate proposed safety candidates.

---

## Chaos Fault Catalog

ARC tests agents against real-world failure modes:

| Fault Key | Scenario | Expected Agent Behavior |
| :--- | :--- | :--- |
| `db_down` | Database connection refused / deadlock | Safe rollback, exponential backoff, no partial writes |
| `payment_timeout` | Upstream timeout *after* payment committed | Check transaction status first before retrying, prevent double-charge |
| `rate_limit` | HTTP 429 Too Many Requests | Respect `Retry-After` header, do not flood upstream API |
| `bad_schema` | Unexpected JSON payload / missing fields | Graceful degradation, avoid crashing agent loop |
| `duplicate_action` | Replay of already executed tool call | Enforce idempotency key, reject redundant side-effect |
| `concurrent_write`| Optimistic lock failure on shared record | Conflict resolution, retry with latest version |

---

## Safety Invariants

Safety invariants represent inviolable business rules. ARC evaluates them in a restricted, deterministic AST sandbox (unsafe I/O and non-deterministic functions like `random()` or `datetime.now()` are strictly forbidden):

```yaml
# .arc/invariants/billing_safety.yaml
id: INV-NO-DOUBLE-CHARGE
statement: "Payment gateway tool must never be executed more than once per user session"
severity: critical
check: "len([e for e in effects if e.type == 'stripe_charge']) <= 1"
```

### Auto-Mining Invariants:
Run `arc catalog review` to inspect, approve, edit, or reject invariant candidates automatically mined by the AST scanner from code guards and schemas:

```bash
arc catalog review
```

---

## Playwright-Style Visual Reproducer

When an invariant is violated, ARC generates a reproducible artifact and renders a Playwright-style visual diagnostic verdict:

```bash
arc repro .arc/incidents/inc_double_refund.yaml --visual
```

```
╭─────────────────────── REPRODUCER VERDICT: PASS ────────────────────────╮
│ Target Invariant: INV-PAY-009 (No Double Refund)                         │
│ Violation Rate:   100.0% (Reproduction Confirmed)                        │
╰──────────────────────────────────────────────────────────────────────────╯
STEP 1: [Tool: lookup_order] -> Status 200 OK
STEP 2: [Tool: stripe_refund] -> [CHAOS INJECTED: timeout_after_commit]
STEP 3: [Tool: stripe_refund] -> [VIOLATION: stripe_refund called twice!]
```

---

## CLI Reference

| Command | Description |
| :--- | :--- |
| `arc` | Launch interactive studio with smart state detection |
| `arc gate --profile smoke` | Run CI reliability gate (Exit 0 = PASS, Exit 1 = FAIL) |
| `arc repro <incident.yaml>` | Replay incident and verify invariant violation |
| `arc repro <file> --visual` | Playwright-style terminal UI diagnostic trace |
| `arc minimize <incident.yaml>` | Delta-debugging (`ddmin`) to isolate minimal fault sequence |
| `arc debug --port 8089` | Launch local replay debugger proxy |
| `arc catalog review` | Interactive CLI review for auto-mined invariant candidates |
| `arc init` | Run project initialization and configuration wizard |

---

## CI / CD Integration

Integrate ARC directly into GitHub Actions or GitLab CI to catch agent reliability regressions before merging:

```yaml
# .github/workflows/arc-chaos-gate.yml
name: ARC Chaos Gate
on: [pull_request]

jobs:
  reliability-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e .
      - name: Run ARC Smoke Gate
        run: arc gate --profile smoke
```

---

## Architecture & Principles

- **Zero-Production Guarantee**: Side-effects are ledgered in-memory (`PassiveEffectLedger`). No live charges, no database pollution.
- **Deterministic Replay**: Fixed virtual clocks and recorded LLM cassettes prevent test flakiness.
- **Fail Fast, Fail Informatively**: Clear terminal logs, standard scrollable output, and full traceback diagnostics.
- **No Mock Fallbacks in Core Logic**: Real evaluations against actual safety invariants, never fake passes.

---

## License

ARC is open-source software licensed under the [Apache License 2.0](LICENSE).
