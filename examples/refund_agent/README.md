# Reference Implementation: `refund-agent`

End-to-end reference application for **Order #8842** double-refund defect reproduction under `timeout_after_commit` fault injection.

## 📌 Overview

This example demonstrates the complete ARC Agent Reliability Harness lifecycle:
1. **Trace Capture**: Capture agent execution traces via `arc_sdk` (`@trace_agent`, `@trace_tool`).
2. **Nominal Execution**: Execute Order #8842 refund workflow cleanly ($45.99).
3. **Chaos Execution & Invariant Violation**: Inject `timeout_after_commit` fault at tool `issue_refund`. The agent retries without an idempotency key, resulting in a **double refund** ($91.98 total) that violates invariant **`INV-PAY-002`**.
4. **Minimal Reproducer Generation**: Reduce fault sequence with `ddmin` to produce `arc-repro-8842.yaml`.
5. **Replay & Verification**: Replay the minimal reproducer instantly via `arc repro`.

---

## ⚡ Quickstart Walkthrough (< 15 Minutes)

### Step 1: Run Nominal Agent Workflow
Execute the standard refund workflow for Order #8842 without any fault injection:

```bash
python3 examples/refund_agent/agent.py
```

Expected Output:
```text
Executing Nominal refund-agent workflow...
Nominal Status: completed
Effects count: 1
```

In nominal mode, 1 financial refund effect for $45.99 is recorded. Invariant `INV-PAY-002` evaluates to `passed`.

---

### Step 2: Chaos Injection & Double Refund Reproduction
Run the chaos workflow where fault `timeout_after_commit` is injected at `issue_refund`:

```python
from agent import run_refund_agent

# Run agent with fault injection
res = run_refund_agent(order_id="8842", inject_fault=True)
print("Effects recorded:", len(res["effects"]))
# Output: 2 effects recorded (Total refunded: $91.98 > Order total $45.99)
```

Expected Output:
```text
Executing Chaos refund-agent workflow (timeout_after_commit)...
Chaos Status: completed
Effects count: 2
```

---

### Step 3: Run Parallel Fork-Replay Engine & Verify Wilson Score
Launch the Parallel Fork Engine with 20 parallel branches to evaluate empirical reproduce rate $p=0.35$ (7/20 branches):

```python
from execution.fork_engine.orchestrator import ForkOrchestrator

orchestrator = ForkOrchestrator(k=20)
# Fork run evaluates invariant INV-PAY-002 across branches
```

---

### Step 4: Generate Minimal Reproducer YAML
Export the minimal reproducer spec `arc-repro-8842.yaml`:

```bash
# Generated artifact location
cat examples/refund_agent/arc-repro-8842.yaml
```

---

### Step 5: Instant CLI Replay
Replay the defect using the CLI `arc repro` command:

```bash
arc repro --config examples/refund_agent/arc-repro-8842.yaml
```

---

## 🛡️ Invariant Specification: `INV-PAY-002`

```yaml
id: INV-PAY-002
statement: "Total financial.refund effects for an order must not exceed order total value"
category: conservation
severity: critical
check: |
  sum(abs(e.delta.amount_cents) for e in effects
      if e.type == "financial.refund" and (e.resource == order.ref or e.resource == ("order:" + str(order.order_id))))
  <= order.total_cents
```

---

## 📂 File Structure

- `agent.py`: Agent source code decorated with `arc_sdk` interceptors.
- `bundle.json`: Signed HarnessBundle conforming to `bundle_v1.json` schema.
- `arc-repro-8842.yaml`: Minimal reproducer YAML artifact.
- `README.md`: Local walkthrough guide.
