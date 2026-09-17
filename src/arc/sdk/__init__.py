"""arc_sdk: Python Interceptor SDK for ARC Plus Platform.

Provides automatic trace capture, tool call redaction, OpenTelemetry span creation,
Canonical Trace Format (CTF v1.0) export, Virtual Clock, and Deterministic RNG.
"""

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
    "get_current_trace",
    "get_current_trace_context",
    "pin_model_params",
    "redact_payload",
    "trace_agent",
    "trace_tool",
]
