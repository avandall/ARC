"""arc_sdk: Python Interceptor SDK for ARC Plus Platform.

Provides automatic trace capture, tool call redaction, OpenTelemetry span creation,
and Canonical Trace Format (CTF v1.0) export.
"""

from arc_sdk.interceptor import (
    TraceContext,
    get_current_trace,
    get_current_trace_context,
    trace_agent,
    trace_tool,
)
from arc_sdk.redactor import (
    DEFAULT_RULES,
    RedactionRule,
    Redactor,
    redact_payload,
)

__all__ = [
    "DEFAULT_RULES",
    "RedactionRule",
    "Redactor",
    "TraceContext",
    "get_current_trace",
    "get_current_trace_context",
    "redact_payload",
    "trace_agent",
    "trace_tool",
]
