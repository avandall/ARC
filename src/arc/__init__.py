"""ARC: Autonomous Reliability & Chaos Harness for AI Agents.

A deterministic simulation and chaos-engineering test harness for production AI agents
that perform real-world side effects (calling APIs, executing DB transactions,
issuing payments, modifying cloud infrastructure).

Basic Usage:
    >>> from arc import trace_agent, trace_tool
    >>>
    >>> @trace_tool(name="order_db")
    ... def lookup_order(order_id: str) -> dict:
    ...     return {"order_id": order_id, "status": "active"}
    >>>
    >>> @trace_agent(name="support_agent")
    ... def handle_ticket(order_id: str) -> dict:
    ...     return lookup_order(order_id)
    >>>
    >>> result = handle_ticket("ORD-1042")
    >>> print(result["status"])
    active

Subpackages:
    arc.sdk: Tracing decorators, virtual clocks, RNG control, and PII redactor.
    arc.execution.sandbox_runner: Zero-prod Docker & UDS sandbox runner with passive ledger.
    arc.execution.fork_engine: K-parallel fork replay, chaos fault injection, and ddmin.
    arc.execution.invariant_engine: Restricted AST CEL-like invariant verification & quarantine.
    arc.execution.tool_models: Stateful domain mock models for zero-prod simulation.
    arc.control_plane.warehouse: Metadata database, S3 content-addressed blob store, and signed bundles.
    arc.control_plane.miner: Automated invariant mining from AST, schemas, and postmortems.
    arc.cli: Unified command-line application (arc gate, repro, minimize, debug, catalog).
"""

from __future__ import annotations

__version__ = "0.1.2"
__author__ = "ARC Team"
__license__ = "Apache-2.0"

from arc.sdk.clock import (
    DeterministicRNG,
    VirtualClock,
    VirtualClockError,
    pin_model_params,
)
from arc.sdk.interceptor import (
    TraceContext,
    get_current_trace,
    get_current_trace_context,
    trace_agent,
    trace_tool,
)
from arc.sdk.redactor import (
    DEFAULT_RULES,
    RedactionRule,
    Redactor,
    calculate_shannon_entropy,
    redact_payload,
)

__all__ = [
    "DEFAULT_RULES",
    "DeterministicRNG",
    "RedactionRule",
    "Redactor",
    "TraceContext",
    "VirtualClock",
    "VirtualClockError",
    "__author__",
    "__license__",
    "__version__",
    "calculate_shannon_entropy",
    "get_current_trace",
    "get_current_trace_context",
    "pin_model_params",
    "redact_payload",
    "trace_agent",
    "trace_tool",
]
