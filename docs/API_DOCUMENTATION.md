# ARC (Agent Reliability & Conformance Harness) — API & Function Reference

A comprehensive, detailed technical reference for all modules, classes, and functions across the **ARC** framework.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [SDK Module (`arc.sdk`)](#2-sdk-module-arcsdk)
   - [Tracing & Instrumentation (`arc.sdk.interceptor`)](#21-tracing--instrumentation-arcsdkinterceptor)
   - [Virtual Clock & Deterministic RNG (`arc.sdk.clock`)](#22-virtual-clock--deterministic-rng-arcsdkclock)
   - [Tier-1 Redaction & Secret Sanitization (`arc.sdk.redactor`)](#23-tier-1-redaction--secret-sanitization-arcsdkredactor)
3. [Sandbox Runner (`arc.execution.sandbox_runner`)](#3-sandbox-runner-arcexecutionsandbox_runner)
   - [Sandbox Container & Runner (`runner.py`)](#31-sandbox-container--runner-runnerpy)
   - [Passive Effect Ledger (`passive_ledger.py`)](#32-passive-effect-ledger-passive_ledgerpy)
   - [Cassette Player & Matchers (`cassette_player.py`)](#33-cassette-player--matchers-cassette_playerpy)
   - [System Clock Interceptor (`clock_interceptor.py`)](#34-system-clock-interceptor-clock_interceptorpy)
   - [Security Sandbox & HMAC Signatures (`security.py`)](#35-security-sandbox--hmac-signatures-securitypy)
4. [Chaos & Fork-Replay Engine (`arc.execution.fork_engine`)](#4-chaos--fork-replay-engine-arcexecutionfork_engine)
   - [Fork Orchestrator (`orchestrator.py`)](#41-fork-orchestrator-orchestratorpy)
   - [Fault Catalog & Fault Specifications (`fault_catalog.py`)](#42-fault-catalog--fault-specifications-fault_catalogpy)
   - [Fault Injector (`injector.py`)](#43-fault-injector-injectorpy)
   - [CI Gate Evaluator (`gate_evaluator.py`)](#44-ci-gate-evaluator-gate_evaluatorpy)
   - [Budget Enforcer (`budget.py`)](#45-budget-enforcer-budgetpy)
   - [Delta Debugging Algorithm (`delta_debugging.py`)](#46-delta-debugging-algorithm-delta_debuggingpy)
   - [Reproducer Exporter (`reproducer_export.py`)](#47-reproducer-exporter-reproducer_exportpy)
   - [Regression Test Generator (`regression_generator.py`)](#48-regression-test-generator-regression_generatorpy)
   - [Statistical Metrics & Wilson Scores (`stats.py`)](#49-statistical-metrics--wilson-scores-statspy)
5. [Invariant Engine (`arc.execution.invariant_engine`)](#5-invariant-engine-arcexecutioninvariant_engine)
   - [Deterministic Invariant Evaluator (`evaluator.py`)](#51-deterministic-invariant-evaluator-evaluatorpy)
   - [Quarantine Manager & Shadow Execution (`quarantine.py`)](#52-quarantine-manager--shadow-execution-quarantinepy)
6. [Tool Models & Domain Simulators (`arc.execution.tool_models`)](#6-tool-models--domain-simulators-arcexecutiontool_models)
   - [Base Tool Model (`base.py`)](#61-base-tool-model-basepy)
   - [Database Domain Simulator (`mock_database.py`)](#62-database-domain-simulator-mock_databasepy)
   - [Payment Domain Simulator (`mock_payment.py`)](#63-payment-domain-simulator-mock_paymentpy)
7. [Control Plane (`arc.control_plane`)](#7-control-plane-arccontrol_plane)
   - [Trace Warehouse & Stores (`warehouse/`)](#71-trace-warehouse--stores-warehouse)
   - [Harness Bundle Generator & Signer (`bundle_generator.py`)](#72-harness-bundle-generator--signer-bundle_generatorpy)
   - [Escaped Bugs Tracking (`escaped_bugs.py`)](#73-escaped-bugs-tracking-escaped_bugspy)
   - [Invariant Mining Engine (`miner/`)](#74-invariant-mining-engine-miner)
   - [Approval Gateway (`approval_gateway/`)](#75-approval-gateway-approval_gateway)
   - [Trace Collector REST API (`collector/`)](#76-trace-collector-rest-api-collector)
8. [CLI Application & Debugger Proxy (`arc.cli`)](#8-cli-application--debugger-proxy-arccli)
   - [Command Reference](#81-command-reference)
   - [Local Debugger Proxy (`debugger_proxy.py`)](#82-local-debugger-proxy-debugger_proxypy)
9. [End-to-End Walkthrough](#9-end-to-end-walkthrough)

---

## 1. Architecture Overview

ARC (*Autonomous Reliability & Chaos Harness for AI Agents*) provides deterministic simulation, chaos fault injection, invariant verification, and trace minimization for autonomous agents:

```
+-------------------------------------------------------------------------+
|                                ARC SDK                                  |
|   @trace_agent            @trace_tool           VirtualClock / Redactor |
+------------------------------------+------------------------------------+
                                     | (Emits CTF v1.0 Traces)
                                     v
+-------------------------------------------------------------------------+
|                           Control Plane                                 |
|  Collector REST API  -->  TraceWarehouse (Postgres + S3 Blob Store)     |
|  Approval Gateway    <--  Miners (AST, SQL DDL, OpenAPI, Postmortem)    |
+------------------------------------+------------------------------------+
                                     | (Harness Bundle export)
                                     v
+-------------------------------------------------------------------------+
|                          Execution Engine                               |
|  +-------------------------------------------------------------------+  |
|  | SandboxRunner (Docker/UDS network-isolated environment)           |  |
|  | - CassettePlayer (Exact Hash -> Masking -> ToolModel -> Abort)   |  |
|  | - PassiveEffectLedger (Traps mutating calls without side-effects) |  |
|  +---------------------------------+---------------------------------+  |
|                                    |                                    |
|  +---------------------------------v---------------------------------+  |
|  | Fork Engine (K-parallel branch simulation)                        |  |
|  | - FaultInjector (Infra, Semantic, Concurrency faults)             |  |
|  | - InvariantEvaluator (Restricted AST, CEL-like evaluation)        |  |
|  | - Wilson Score CIs & CI Quality Gate (Exit Codes 0, 1, 2, 3)     |  |
|  | - ddmin: Delta-Debugging bug reproducer minimization              |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
```

---

## 2. SDK Module (`arc.sdk`)

The SDK instruments agent workflows, capturing step-by-step executions into the **Canonical Trace Format (CTF v1.0)**.

### 2.1 Tracing & Instrumentation (`arc.sdk.interceptor`)

#### `class TraceContext`
Manages trace state across an agent execution session.

- **`__init__(trace_id: str | None = None, agent_name: str = "default_agent", agent_version: str = "1.0.0", model_provider: str = "openai", model_id: str = "gpt-4o")`**
  - Initializes a new tracing context with a unique trace ID, timestamps, and model parameters.
- **`add_step(step: dict[str, Any]) -> None`**
  - Appends a step dictionary (tool invocation or agent decision) to the trace.
- **`to_ctf_dict() -> dict[str, Any]`**
  - Formats current context into a valid CTF v1.0 payload, calculating execution duration (`wall_ms`), final status, and redaction key identifier.

#### `get_current_trace_context() -> TraceContext | None`
- Retrieves the active thread-local/asyncio `TraceContext` from `ContextVar`. Returns `None` if execution is outside a `@trace_agent` scope.

#### `get_current_trace() -> dict[str, Any] | None`
- Returns the active trace formatted as a CTF v1.0 dictionary.

#### `push_trace_to_collector(trace_payload: dict[str, Any], collector_url: str, timeout: float = 3.0) -> bool`
- Sends a completed CTF payload to the ARC Collector REST API via HTTP POST.
- **Returns:** `True` on HTTP 200/201/202, `False` on connection failures or timeouts.

#### `class trace_agent`
Decorator and context manager wrapping high-level agent routines.

- **Parameters:**
  - `name: str = "default_agent"`: Identifying name of the agent.
  - `version: str = "1.0.0"`: Version string of the agent implementation.
  - `trace_id: str | None = None`: Optional explicit trace ID. If omitted, generates a random UUIDv4.
  - `model_provider: str = "openai"`: LLM provider name (e.g., `"openai"`, `"anthropic"`, `"google"`).
  - `model_id: str = "gpt-4o"`: Specific model identifier.
  - `collector_url: str | None = None`: URL of the ARC Collector. If omitted, checks `ARC_COLLECTOR_URL` environment variable.
- **Behavior:**
  - Creates an OpenTelemetry span `arc.agent.<name>`.
  - Sets thread/coroutine context.
  - Automatically captures uncaught exceptions, marks `outcome_status="agent_error"`, and pushes trace to the collector upon exit.

```python
from arc.sdk import trace_agent

@trace_agent(name="refund_assistant", version="2.1.0", model_id="gpt-4o")
def handle_refund_request(order_id: str, amount: float) -> dict:
    # Agent logic...
    return {"status": "success", "order_id": order_id}

# Or as context manager:
with trace_agent(name="batch_processor") as ctx:
    do_work()
```

#### `trace_tool(name: str | Callable | None = None, redactor: Redactor | None = None, trap_exceptions: bool = True) -> Callable`
Decorator wrapping individual tool functions invoked by agents.

- **Parameters:**
  - `name`: Custom tool name override. If omitted, uses `func.__name__`.
  - `redactor`: Custom `Redactor` instance for sanitizing tool arguments and return values. Defaults to global `Redactor`.
  - `trap_exceptions`: When `True` (default), traps exceptions raised by the tool and returns a synthetic error payload `{"status": "error", "error": str(exc)}`, preventing the agent process from crashing. When `False`, re-raises after recording the trace step.
- **Records:**
  - `step_id`: Monotonically increasing step counter.
  - `t_virtual_ms`: Elapsed virtual time in milliseconds.
  - `request.args`: Fully redacted input arguments.
  - `response.body`: Sanitized result payload.
  - `latency_ms`: Execution time in milliseconds.

```python
from arc.sdk import trace_tool

@trace_tool(name="execute_refund", trap_exceptions=True)
def execute_refund(account_id: str, amount_cents: int) -> dict:
    # Business logic...
    return {"refund_id": "ref_9921", "amount": amount_cents}
```

---

### 2.2 Virtual Clock & Deterministic RNG (`arc.sdk.clock`)

Eliminates non-determinism caused by system wall-clock access and random number generators during replays.

#### `class VirtualClock`
Deterministic virtual clock for managing timelines in replay sandboxes.

- **`__init__(initial_time: datetime | str | float | None = None)`**
  - Accepts ISO timestamp strings (e.g. `"2026-09-17T14:00:00Z"`), datetime objects, or Unix epoch numbers. Defaults to current UTC time.
- **`now() -> datetime`**
  - Returns current virtual time as a timezone-aware UTC `datetime`.
- **`time() -> float`**
  - Returns current virtual time as Unix epoch seconds (`float`).
- **`advance(delta_ms: float) -> datetime`**
  - Advances virtual time forward by `delta_ms` milliseconds.
  - **Raises:** `VirtualClockError` if `delta_ms < 0` (backward drift is strictly forbidden during replay).
- **`sleep(seconds: float) -> None`**
  - Simulates execution sleep without blocking the OS thread, advancing virtual time by `seconds * 1000`.

```python
from arc.sdk.clock import VirtualClock

clock = VirtualClock("2026-10-01T00:00:00Z")
assert clock.time() == 1790812800.0

clock.advance(1500)  # +1.5s
assert clock.now().isoformat() == "2026-10-01T00:00:01.500000+00:00"
```

#### `class DeterministicRNG`
Thread-safe, reproducible pseudo-random generator wrapping Python's `random.Random`.

- **`seed(seed: int = 42) -> None`**: Resets internal state to specified seed.
- **`random() -> float`**: Generates next float in `[0.0, 1.0)`.
- **`randint(a: int, b: int) -> int`**: Generates integer in `[a, b]`.
- **`uniform(a: float, b: float) -> float`**: Generates float in `[a, b)`.
- **`choice(seq: Sequence[T]) -> T`**: Selects single element uniformly.
- **`sample(population: Sequence[T], k: int) -> list[T]`**: Samples `k` unique elements.

#### `pin_model_params(params: dict[str, Any] | None = None, seed: int = 42) -> dict[str, Any]`
Pins model parameters for deterministic replay by enforcing `temperature = 0.0` and `seed = 42`.

---

### 2.3 Tier-1 Redaction & Secret Sanitization (`arc.sdk.redactor`)

Scans and sanitizes credentials, tokens, and PII in-memory before trace serialization to prevent leakage.

#### `class RedactionRule`
- **`create(rule_id: str, regex_pattern: str) -> RedactionRule`**: Factory method compiling a named regex pattern with replacement placeholder `[REDACTED:<rule_id>]`.

#### `DEFAULT_RULES`
Built-in rule definitions:
1. `stripe_live_key`: `sk_live_[0-9a-zA-Z]{24,}`
2. `stripe_test_key`: `sk_test_[0-9a-zA-Z]{24,}`
3. `aws_key`: `AKIA[0-9A-Z]{16}`
4. `generic_bearer`: `Bearer\s+[A-Za-z0-9\-._~+/]+=*`
5. `jwt_token`: Standard 3-part Base64 URL JWT string

#### `calculate_shannon_entropy(s: str) -> float`
- Computes Shannon entropy $H(X) = -\sum p(x) \log_2 p(x)$ of an input string to identify high-entropy random API secrets and private keys.

#### `class Redactor`
- **`__init__(rules: list[RedactionRule] | None = None, enable_entropy_check: bool = False, entropy_threshold: float = 4.5, min_entropy_length: int = 20)`**
- **`redact_text(text: str) -> str`**: Sanitizes string using regex rules and optional Shannon entropy thresholding.
- **`redact(data: Any, seen: set[int] | None = None) -> Any`**: Recursively traverses nested dictionaries, lists, sets, and tuples, replacing sensitive strings and preventing infinite loops on circular references with `"[CIRCULAR]"`.

#### `redact_payload(data: Any) -> Any`
- Convenience helper redacting payload with global default rules.

---

## 3. Sandbox Runner (`arc.execution.sandbox_runner`)

Executes agents in isolated environments with zero egress to production networks.

### 3.1 Sandbox Container & Runner (`runner.py`)

#### `class ReplayMode(str, Enum)`
- `PASSIVE`: Traps mutating tool calls into `PassiveEffectLedger`. No cassette lookups or fault injections.
- `FAULT_ONLY`: Applies faults directly without matching recorded cassette responses.
- `CASSETTE_THEN_FAULT`: Standard deterministic replay mode. Replays baseline response from cassette; then `FaultInjector` overlays fault behavior on top.

#### `class SandboxRunner`
Manages sandbox environment creation, HMAC verification, and test execution.

- **`__init__(config: SandboxConfig | None = None, ledger: PassiveEffectLedger | None = None)`**
- **`start_container(...) -> SandboxContainer`**
  - Validates bundle HMAC signatures.
  - Scans environment variables for leaked production keys via `scan_credentials()`.
  - Spawns an isolated `SandboxContainer`.
- **`run_with_faults(fault_spec: list[dict] | FaultCatalog, target_invariant: str | InvariantSpec | dict, cassette_player: CassettePlayer | None = None, context: dict | None = None, replay_mode: ReplayMode = ReplayMode.CASSETTE_THEN_FAULT) -> dict[str, Any]`**
  - Primary execution method for replaying bug reproducers.
  - **Returns:**
    - `status`: `"violation_reproduced"` or `"ok"`
    - `violated_invariant`: Invariant ID string
    - `passed`: `bool` (`True` if invariant was satisfied)
    - `effects`: List of recorded ledger entries
    - `eval_result`: `EvaluationResult` dictionary

#### `class SandboxContainer`
- **`execute_request(url: str, method: str = "GET", ...) -> dict`**: Validates outbound target against allowed proxy addresses (`arc-proxy:8089`, `localhost`). Raises `TimeoutError` (Egress Denied) if external traffic is attempted.
- **`execute_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]`**: Routes tool execution through `FaultInjector.intercept_tool_call()` before logging deltas into `PassiveEffectLedger`.

---

### 3.2 Passive Effect Ledger (`passive_ledger.py`)

Records state transitions and side-effects in memory without executing actual production writes.

#### `is_mutating_tool(tool_name: str) -> bool`
- Checks whether a tool performs mutations based on keywords: `refund`, `delete`, `update`, `create`, `cancel`, `transfer`, `pay`, `charge`, `post`, `write`, `execute`.

#### `class PassiveEffectLedger`
- **`record_effect(tool_name: str, arguments: dict, step_id: int | None = None, resource: str | None = None, effect_type: str | None = None, delta: dict | None = None, reversible: bool = True, idempotency_key: str | None = None, observed_at_step: int | None = None) -> dict[str, Any]`**
  - Records an effect entry conforming to `schemas/json/effect_v1.json`. Automatically infers resource IDs (e.g. `order:8842` from `{"order_id": 8842}`).
- **`trap_mutating_call(tool_name: str, arguments: dict, mock_response: dict | None = None, step_id: int | None = None) -> dict[str, Any]`**
  - Records effect in ledger and returns a synthetic successful response (`{"status": "ok", "message": "Mutating call trapped..."}`).
- **`get_effects() -> list[dict[str, Any]]`**: Returns all recorded effects.
- **`clear() -> None`**: Flushes ledger and resets monotonic step counter.

---

### 3.3 Cassette Player & Matchers (`cassette_player.py`)

Deterministic playback engine implementing a 4-tier lookup strategy:

```
Tool Request ---> [Strategy 1: Exact SHA-256 Canonical Hash] ---> MATCH: Return Response
                          |
                         MISS
                          v
                  [Strategy 2: Rule-based Masking Matcher]     ---> MATCH: Return Response
                  (strips timestamp, nonce, request_id, etc.)
                          |
                         MISS
                          v
                  [Strategy 3: Tool Model Fallback]            ---> MATCH: Run Simulator
                          |
                         MISS
                          v
                  [Strategy 4: Transparent Abort]             ---> Raise CassetteMissException
```

#### `class CassettePlayer`
- **`__init__(records: list[CassetteRecord | dict] | None = None, dynamic_fields: set[str] | None = None, tool_models: dict | None = None)`**
- **`add_record(record: CassetteRecord | dict) -> None`**: Appends recorded tool interaction.
- **`register_tool_model(tool_name: str, model_fn: Callable) -> None`**: Registers domain model fallback simulator.
- **`replay(tool_name: str, args: dict[str, Any]) -> dict[str, Any]`**: Executes 4-tier match strategy. Raises `CassetteMissException` on miss.
- **`cassette_miss_rate -> float`**: Property returning fraction of requests that missed (`miss_count / total_requests`).

#### `mask_dynamic_fields(data: Any, dynamic_fields: set[str] | None = None) -> Any`
- Strips variable parameters (timestamps, nonces, request IDs) for stable semantic matching.

---

### 3.4 System Clock Interceptor (`clock_interceptor.py`)

#### `intercept_system_clock(clock: VirtualClock) -> Generator[ClockInterceptor, None, None]`
- Context manager monkey-patching `datetime.datetime.now` and `datetime.datetime.utcnow` to return time from the specified `VirtualClock`.

---

### 3.5 Security Sandbox & HMAC Signatures (`security.py`)

- **`compute_hmac_signature(bundle_data: Any, secret: str | bytes) -> str`**: Computes SHA-256 HMAC over canonical JSON bytes.
- **`verify_bundle_signature(bundle_data: Any, secret: str | bytes, expected_signature: str | None = None) -> bool`**: Verifies bundle integrity; raises `InvalidSignatureError` on tampering.
- **`scan_credentials(env_vars: dict | None = None, content: Any = None) -> list[str]`**: Scans dictionaries and text for production credential strings, raising `SecurityViolationError` if found.

---

## 4. Chaos & Fork-Replay Engine (`arc.execution.fork_engine`)

Enables parallel branch simulation from intermediate execution fork points to test resilience against systemic faults.

### 4.1 Fork Orchestrator (`orchestrator.py`)

#### `class ForkOrchestrator`
Runs $K$ parallel independent branches from a fork point, collecting ledger effects and computing 95% Wilson Score Confidence Intervals.

- **`__init__(k: int = 20, budget_usd: float | None = None, budget_tokens: int | None = None, max_seconds: float | None = None, max_workers: int = 20, invariant_catalog: list[dict] | None = None)`**
  - Configures sample count $K$, resource budgets, thread pool size, and invariant catalog for automatic evaluation on branch effect ledgers.
- **`run_fork(fault_spec: FaultSpec | dict, branch_executor: Callable | None = None, run_id: str | None = None) -> ForkRunResult`**
  - Concurrently dispatches $K$ branches via `ThreadPoolExecutor`.
  - Aborts execution if `BudgetEnforcer` limits are exceeded.
  - Automatically evaluates invariants on returned branch `effects` via `InvariantEvaluator`.
  - Aggregates violation rates and computes Wilson Score Confidence Intervals $[CI_{lower}, CI_{upper}]$.

#### `class ForkRunResult`
Holds execution statistics:
- `k`: Requested branches.
- `n_valid`: Number of valid branch completions.
- `n_min`: Minimum required valid branches for statistical confidence ($N_{min} = \lceil 0.8 \cdot K \rceil$).
- `n_miss`: Branches aborted due to cassette misses.
- `n_infra`: Branches failed due to infrastructure errors.
- `n_budget`: Branches aborted by budget enforcer.
- `violations`: Dictionary mapping invariant IDs to violation count and Wilson CIs.

---

### 4.2 Fault Catalog & Fault Specifications (`fault_catalog.py`)

#### `class FaultType(str, Enum)`
- **Group A (Infrastructure):**
  - `TIMEOUT_BEFORE_COMMIT`: Network timeout before mutation is committed (ledger records 0 effects).
  - `TIMEOUT_AFTER_COMMIT`: Network timeout after mutation is committed (ledger records 1 effect, returns 504).
  - `HTTP_500`, `HTTP_502`, `HTTP_429`: HTTP status code errors.
  - `LATENCY_SPIKE`: Delays call execution by `delay_ms`.
- **Group B (Semantic):**
  - `BAD_SCHEMA`: Injects malformed structure or unexpected fields.
  - `REQUIRED_FIELD_NULL`: Forces a mandatory field to `None`.
  - `EMPTY_LIST`: Replaces an array/list with `[]`.
  - `TYPE_COERCION`: Converts numerical values to strings.
  - `BOUNDARY_VALUE`: Overrides fields with extreme min/max values.
- **Group C (Concurrency & Idempotency):**
  - `DUPLICATE_ACTION`: Executes tool twice to test idempotency handling.
  - `PARTIAL_SUCCESS`: First write commits; second write fails.
  - `CONCURRENT_WRITE`: Simulates concurrent resource modification (returns HTTP 409).

#### `class FaultSpec`
- **`__init__(at_step: int, fault_type: str | FaultType, target_tool: str | None = None, params: dict | None = None, fault_id: str | None = None)`**

#### `class FaultCatalog`
- Registry managing single and compound fault chains (`add_fault()`, `add_compound_faults()`, `get_faults_for_step()`).

---

### 4.3 Fault Injector (`injector.py`)

#### `class FaultInjector`
Intercepts tool calls during sandboxed replay and executes matching `FaultSpec` instructions.

- **`__init__(catalog: FaultCatalog | Sequence | None = None, ledger: PassiveEffectLedger | None = None)`**
- **`intercept_tool_call(step_id: int, tool_name: str, args: dict, default_executor: Callable | None = None) -> dict[str, Any]`**
  - Inspects catalog for faults configured at `step_id` for `tool_name`.
  - If a fault matches, executes fault logic (e.g. sleeping, returning error status, recording partial effects) and marks fault as applied.
  - If no fault matches, executes standard tool behavior or passive ledger trap.

---

### 4.4 CI Gate Evaluator (`gate_evaluator.py`)

#### `class CIGateExitCode(IntEnum)`
POSIX-compliant exit codes for CI/CD pipelines:
- `SUCCESS = 0`: All invariants satisfied or violation rates overlap baseline CI.
- `CRITICAL_VIOLATION = 1`: Confirmed critical invariant violation (Wilson CI does not overlap baseline).
- `BUDGET_EXCEEDED = 2`: Simulation cost ceiling reached.
- `INFRA_ERROR = 3`: Infrastructure/Docker failure.

#### `check_wilson_overlap(ci_a: tuple[float, float], ci_b: tuple[float, float]) -> bool`
- Evaluates whether two intervals overlap: $\max(A_{low}, B_{low}) \le \min(A_{high}, B_{high})$.

#### `class GateEvaluator`
- **`__init__(profile: str = "smoke", budget_usd: float | None = None, baseline_ci: tuple[float, float] = (0.0, 0.0), invariant_catalog: dict | None = None)`**
  - `profile="smoke"`: Uses $K=3$ branches.
  - `profile="full"`: Uses $K=20$ branches.
- **`evaluate(...) -> GateEvaluationResult`**: Executes fork run and returns verdict and POSIX exit code.

---

### 4.5 Budget Enforcer (`budget.py`)

#### `class BudgetEnforcer`
Tracks simulation resource expenditures.
- **`record_usage(cost_usd: float = 0.0, tokens: int = 0, seconds: float = 0.0) -> bool`**
  - Accumulates resource metrics. Returns `True` if within limits; raises `BudgetExceededException` if ceilings are breached.

---

### 4.6 Delta Debugging Algorithm (`delta_debugging.py`)

#### `ddmin(faults: list[T], test_fn: Callable[[list[T]], bool]) -> list[T]`
Implements Zeller's Delta Debugging (`ddmin`) algorithm to minimize fault chains.

- **Parameters:**
  - `faults`: Initial list of candidate faults.
  - `test_fn`: Predicate returning `True` if a subset of faults still triggers the invariant violation.
- **Returns:** The 1-minimal fault sequence required to reproduce the bug.
- **Raises:** `IrreproducibleBugError` if the full fault sequence fails to reproduce the bug initially.

---

### 4.7 Reproducer Exporter (`reproducer_export.py`)

#### `export_minimal_reproducer_yaml(trace: str, faults: list[dict], violated: str, determinism_level: str = "L1", reproduce_rate: float = 1.0, confidence_interval: list[float] | None = None, cost_usd: float = 0.0, output_path: str | Path | None = None) -> Path`
- Exports a minimal reproducer artifact in YAML format adhering to `schemas/json/reproducer_v1.json`.

---

### 4.8 Regression Test Generator (`regression_generator.py`)

#### `class RegressionTestGenerator`
- **`generate_from_yaml(yaml_path: str | Path, output_path: str | Path | None = None) -> Path`**
  - Reads an `arc-repro-*.yaml` artifact and generates a standalone, runnable pytest file in `tests/regression/test_arc_regression_<id>.py`.

---

### 4.9 Statistical Metrics & Wilson Scores (`stats.py`)

- **`calculate_wilson_score(violations: int, n_valid: int, confidence: float = 0.95) -> tuple[float, float]`**
  - Computes the Wilson Score Interval with continuity correction for binomial proportions:
    $$w = \frac{\hat{p} + \frac{z^2}{2n} \pm z \sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$
- **`compute_n_valid(k: int, n_miss: int = 0, n_infra: int = 0, n_budget: int = 0) -> int`**
  - Calculates $N_{valid} = K - (N_{miss} + N_{infra} + N_{budget})$.
- **`compute_n_min(k: int) -> int`**
  - Computes minimum acceptable sample size $N_{min} = \lceil 0.8 \cdot K \rceil$.
- **`is_sample_sufficient(n_valid: int, k: int) -> bool`**
  - Returns `True` if $N_{valid} \ge N_{min}$.

---

## 5. Invariant Engine (`arc.execution.invariant_engine`)

The Invariant Engine verifies that agent side-effects satisfy business, financial, and authorization rules.

### 5.1 Deterministic Invariant Evaluator (`evaluator.py`)

#### `class InvariantSpec`
Dataclass defining an invariant:
- `id: str`: Unique identifier (e.g., `"INV-PAY-001"`).
- `statement: str`: Plain English invariant description.
- `category: str`: Must be one of `{"safety", "conservation", "idempotence", "ordering", "authority", "budget", "consistency"}`.
- `check: str`: Python expression evaluated against ledger effects.
- `severity: str`: `"critical"` (blocks CI) or `"warning"`.
- `status: str`: `"active"`, `"quarantined"`, or `"deprecated"`.

#### `class DeterministicASTValidator(ast.NodeVisitor)`
Parses check expressions using Python's AST and enforces strict determinism:
- **Forbidden Calls:** `random`, `randint`, `time`, `now`, `uuid`, `open`, `read`, `write`, `exec`, `eval`, `compile`, etc.
- **Forbidden Constructs:** `import`, `import from`, and dunder attribute access (`__*__`).
- **Raises:** `ForbiddenExpressionError`.

#### `class InvariantEvaluator`
- **`compile(check_expression: str) -> ast.AST`**: Validates expression against `DeterministicASTValidator`.
- **`evaluate(invariant: InvariantSpec | dict, effects: list[dict], context: dict | None = None) -> EvaluationResult`**
  - Evaluates check expression in a sandboxed namespace exposing `effects`, `context`, and `SAFE_BUILTINS` (`sum`, `len`, `min`, `max`, `all`, `any`, etc.).
  - Supports dot notation via `AttrDict` (e.g. `effects[0].delta.amount`).
  - **Returns:** `EvaluationResult(violated=bool, error=str | None, exec_time_ms=float)`.

```python
from arc.execution.invariant_engine.evaluator import InvariantEvaluator, InvariantSpec

evaluator = InvariantEvaluator()

inv = InvariantSpec(
    id="INV-PAY-002",
    statement="Refund amount must never exceed the original charge",
    category="conservation",
    check="sum([e.delta.amount for e in effects if e.type == 'refund']) <= context.order.total_amount",
    severity="critical"
)

effects = [{"type": "refund", "delta": {"amount": 50.0}}]
context = {"order": {"total_amount": 100.0}}

result = evaluator.evaluate(inv, effects, context)
assert not result.violated
```

---

### 5.2 Quarantine Manager & Shadow Execution (`quarantine.py`)

#### `class QuarantineManager`
Manages flaky or noisy invariant rules according to statistical track records.

- **`auto_quarantine_check(invariant: InvariantSpec | dict) -> bool`**
  - Automatically transitions an invariant from `"active"` to `"quarantined"` if precision drops below `precision_threshold = 0.50` after at least `min_triaged = 10` triaged runs.
- **`should_block_ci(invariant: InvariantSpec | dict, evaluation_result: EvaluationResult) -> bool`**
  - Returns `False` for any invariant that is `"quarantined"` or `"deprecated"`, guaranteeing that unverified invariants never break CI merges.
- **`run_shadow_quarantine(invariant, evaluator, effects, context=None) -> tuple[EvaluationResult, bool]`**
  - Executes invariant in shadow mode, updates its precision track record, evaluates auto-quarantine rules, and returns `(result, should_block_ci)`.

---

## 6. Tool Models & Domain Simulators (`arc.execution.tool_models`)

Provides stateful mocks for external services when cassettes do not cover newly explored paths.

### 6.1 Base Tool Model (`base.py`)

#### `class ToolModel(ABC)`
- **`clone_fresh_state(seed_state_ref: str = "") -> ToolModel`**: Returns an isolated, fresh copy of the model state.
- **`handle(request_args: dict[str, Any], injected_fault: dict | None = None) -> dict[str, Any]`**: Handles tool call and applies optional fault.
- **`to_effect_ledger_entries() -> list[dict[str, Any]]`**: Exports recorded internal mutations as ledger effect entries.

---

### 6.2 Database Domain Simulator (`mock_database.py`)

#### `class MockDatabase(ToolModel)`
- Simulates SQL/Key-Value database operations with in-memory tables. Tracks rows, supports simulated transaction commits and rollbacks.

---

### 6.3 Payment Domain Simulator (`mock_payment.py`)

#### `class MockPaymentGateway(ToolModel)`
- Simulates payment gateway transactions (`charge`, `refund`, `lookup_transaction`).
- Emits structured financial effects with idempotency key tracking.

---

## 7. Control Plane (`arc.control_plane`)

### 7.1 Trace Warehouse & Stores (`warehouse/`)

#### `class TraceWarehouse`
Unified storage facade combining database metadata (PostgreSQL/SQLite) and content-addressed blobs (S3/MinIO).

- **`save_trace(ctf_data: dict[str, Any]) -> str`**
  - Computes SHA-256 hashes of arguments and response bodies, stores payload blobs in `BlobStore`, and inserts indexing metadata into `DatabaseStore`.
- **`get_trace(trace_id: str) -> dict[str, Any] | None`**
  - Reconstructs full CTF v1.0 trace dictionary by fetching metadata and rehydrating blob references.
- **`list_traces(agent: str | None = None, outcome_status: str | None = None, since: str | None = None) -> list[dict[str, Any]]`**
  - Queries traces with optional filters.
- **`set_rls_context(allowed_agents: str | None) -> None`**
  - Enforces row-level security (RLS) policies by restricting queries to authorized agent names.

#### `class S3BlobStore`
- **`put(content: Any) -> str`**: Serializes content to canonical bytes, writes to storage with key `sha256:<hash>`, and returns the reference string.
- **`get(ref: str) -> Any | None`**: Retrieves and deserializes blob content.

#### `class DatabaseStore`
- Manages relational tables for traces, steps, effects, invariant candidates, rejected candidate deduplication, and escaped bug incident tracking.

---

### 7.2 Harness Bundle Generator & Signer (`bundle_generator.py`)

#### `class HarnessBundleGenerator`
- **`generate(ctf_data: dict, secret_key: str, key_id: str = "default", max_steps: int = 10000, window_size_around_fork: int = 50) -> dict[str, Any]`**
  - Builds standalone reproduction bundle (`schemas/json/bundle_v1.json`).
  - Truncates oversized traces to a window of $\pm 50$ steps around the fork point.
  - Signs payload with HMAC-SHA256.

#### `class BundleSignatureVerifier`
- **`verify(bundle: dict, secret_key: str, raise_on_error: bool = True) -> bool`**
  - Re-computes canonical signature and verifies tamper-free integrity.

---

### 7.3 Escaped Bugs Tracking (`escaped_bugs.py`)

#### `class EscapedBugTracker`
- **`tag_incident(trace_id: str, escaped_bug: bool = True, linked_invariant: str | None = None, root_cause: str = "", tagged_by: str = "engineer", quarter: str = "2026-Q3") -> dict`**
  - Links a production failure incident to an invariant rule.
- **`calculate_quarterly_escaped_bug_rate(quarter: str | None = None, total_incidents: int | None = None) -> float`**
  - Computes quarterly escaped bug percentage metric: $\frac{\text{Escaped Bugs}}{\text{Total Incidents}} \times 100\%$.

---

### 7.4 Invariant Mining Engine (`miner/`)

Automatically extracts invariant candidates from existing engineering artifacts.

#### `class ASTMiner (ast_miner.py)`
Uses tree-sitter AST parsing to extract invariants from Python source files and SQL DDL schemas.
- **`mine_python_source(code_str: str, filename: str = "") -> list[MinedCandidate]`**
  - Identifies assertions, validation checks, and authorization guards.
- **`mine_sql_ddl(ddl_str: str, filename: str = "") -> list[MinedCandidate]`**
  - Converts `CHECK`, `NOT NULL`, `UNIQUE`, and `FOREIGN KEY` constraints into invariant candidates.

#### `class SchemaMiner (schema_miner.py)`
- **`mine_openapi_spec(spec_input: str | dict, filename: str = "") -> list[MinedCandidate]`**
  - Parses OpenAPI 3.0 / Swagger specifications, extracting parameter bounds (`minimum`, `maximum`, `required`).

#### `class PostmortemMiner (postmortem_miner.py)`
- **`mine_from_postmortem(postmortem_text: str, candidate_drafts: list[dict]) -> dict`**
  - Validates candidate invariants extracted from incident postmortems using `CitationVerifier`.

#### `class CitationVerifier (citation_verifier.py)`
- **`verify_citation(candidate_citation: str, source_document: str, min_similarity: float = 0.92) -> bool`**
  - Uses Levenshtein distance and token similarity to prevent AI hallucination by verifying that cited postmortem excerpts exist in the source document.

#### `class DifferentialProfiler (differential.py)`
- **`profile(error_trace: dict, baseline_traces: list[dict]) -> ProfilingResult`**
  - Highlights differential divergence points between successful baseline traces and failing traces.

---

### 7.5 Approval Gateway (`approval_gateway/`)

#### `class ApprovalGateway`
Enforces human-in-the-loop governance over candidate invariants.

- **`reject_candidate(candidate_id: str, reason: str, rejected_by: str = "engineer", candidate_statement: str | None = None) -> dict`**
  - Saves normalized SHA-256 statement hash into `rejected_candidates` table.
- **`filter_candidates(candidates: list) -> list`**
  - Filters out incoming candidates that match previously rejected hashes to prevent re-mining noise.
- **`sync_catalog(direction: str = "yaml_to_db") -> dict`**
  - Enforces one-way sync boundary (repo YAML $\to$ DB cache). Blocks direct DB-to-YAML writes to preserve Git as the single source of truth.

---

### 7.6 Trace Collector REST API (`collector/`)

FastAPI microservice ingesting CTF traces from distributed agents:
- `POST /v1/collector/traces`: Ingests CTF v1.0 payload. Authenticates via Bearer token (`auth.py`).
- `GET /v1/collector/health`: Service health check.

---

## 8. CLI Application & Debugger Proxy (`arc.cli`)

### 8.1 Command Reference

The unified CLI entry point is `arc`:

```bash
# 1. Evaluate CI Quality Gate on an execution trace
arc gate --profile smoke --budget-usd 5.0 --trace trace_8842.json

# 2. Replay and diagnose a bug reproducer artifact
arc repro arc-repro-8842.yaml

# 3. Minimize a noisy reproducer with Delta Debugging
arc minimize arc-repro-long-chain.yaml --output arc-repro-min.yaml

# 4. Start local Replay Debugger Proxy
arc debug --port 8089

# 5. Review invariant candidates
arc catalog review --id INV-PAY-002 --accept

# 6. Tag an escaped production incident
arc incidents tag INC-1042 --candidate-id INV-PAY-002
```

---

### 8.2 Local Debugger Proxy (`debugger_proxy.py`)

#### `class LocalDebuggerProxy`
In-process MITM HTTP replay proxy for local interactive debugging.

- **`__init__(host: str = "127.0.0.1", port: int = 8089, cassette_player: CassettePlayer | None = None, fault_injector: FaultInjector | None = None)`**
- **`start() -> tuple[int, bool]`**: Starts proxy server on a background daemon thread. Returns `(actual_port, was_started)`.
- **`stop() -> None`**: Gracefully shuts down proxy.
- **`get_env_vars() -> dict[str, str]`**: Returns environment configuration variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`).

---

## 9. End-to-End Walkthrough

### Step 1: Instrument Agent with SDK

```python
from arc.sdk import trace_agent, trace_tool

@trace_tool(name="payment_gateway")
def charge_card(customer_id: str, amount_cents: int) -> dict:
    return {"status": "success", "charge_id": "ch_9821"}

@trace_agent(name="checkout_agent", version="1.0.0")
def checkout(customer_id: str, amount_cents: int) -> dict:
    return charge_card(customer_id, amount_cents)

if __name__ == "__main__":
    result = checkout("cust_44", 2500)
    print("Execution Finished:", result)
```

### Step 2: Test Fault Injection in Local Sandbox

```python
from arc.execution.fork_engine.fault_catalog import FaultCatalog, FaultSpec, FaultType
from arc.execution.sandbox_runner.runner import SandboxRunner

# Configure a network timeout after charge commit
catalog = FaultCatalog()
catalog.add_fault(FaultSpec(
    at_step=1,
    fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
    target_tool="payment_gateway"
))

# Target business safety invariant
target_invariant = {
    "id": "INV-NO-DOUBLE-CHARGE",
    "statement": "Customer must not be charged more than once",
    "category": "safety",
    "check": "len([e for e in effects if e.type == 'payment_gateway']) <= 1",
    "severity": "critical"
}

runner = SandboxRunner()
result = runner.run_with_faults(
    fault_spec=catalog,
    target_invariant=target_invariant
)

print("Sandbox Execution Verdict:", result["status"])
print("Passed:", result["passed"])
```

### Step 3: Run Fork Replay with Confidence Intervals

```python
from arc.execution.fork_engine.orchestrator import ForkOrchestrator
from arc.execution.fork_engine.fault_catalog import FaultSpec, FaultType

orchestrator = ForkOrchestrator(k=20, max_workers=5)
fault = FaultSpec(at_step=1, fault_type=FaultType.TIMEOUT_AFTER_COMMIT)

run_result = orchestrator.run_fork(fault_spec=fault)
print(f"Valid Runs: {run_result.n_valid}/{run_result.k}")
print(f"Violations & Wilson CIs: {run_result.violations}")
```
