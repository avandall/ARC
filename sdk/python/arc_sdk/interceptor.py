"""Interceptor SDK (`arc_sdk`) module.

Provides decorators and context managers for tracing agent execution,
tool calls, OpenTelemetry span integration, and Tier 1 redaction.
"""

from __future__ import annotations

import functools
import time
import traceback
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Literal, TypeVar, cast

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Status, StatusCode

from arc_sdk.redactor import Redactor, redact_payload

F = TypeVar("F", bound=Callable[..., Any])

_tracer = otel_trace.get_tracer("arc_sdk", "0.1.0")


class TraceContext:
    """Quản lý trạng thái trace active trong context hiện tại."""

    def __init__(
        self,
        trace_id: str | None = None,
        agent_name: str = "default_agent",
        agent_version: str = "1.0.0",
        model_provider: str = "openai",
        model_id: str = "gpt-4o",
    ) -> None:
        self.trace_id: str = trace_id or str(uuid.uuid4())
        self.agent_name: str = agent_name
        self.agent_version: str = agent_version
        self.model_provider: str = model_provider
        self.model_id: str = model_id
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self.start_perf: float = time.perf_counter()
        self.steps: list[dict[str, Any]] = []
        self.effects: list[dict[str, Any]] = []
        self.outcome_status: str = "completed"
        self.status_source: str = "agent_self_report"

    def add_step(self, step: dict[str, Any]) -> None:
        self.steps.append(step)

    def to_ctf_dict(self) -> dict[str, Any]:
        wall_ms = round((time.perf_counter() - self.start_perf) * 1000, 2)
        return {
            "trace_id": self.trace_id,
            "session_id": None,
            "agent": {
                "name": self.agent_name,
                "version": self.agent_version,
                "git_sha": None,
            },
            "model": {
                "provider": self.model_provider,
                "model_id": self.model_id,
                "params": None,
            },
            "started_at": self.started_at,
            "determinism_level": "L1",
            "steps": self.steps,
            "effects": self.effects,
            "final_state_ref": None,
            "outcome": {
                "status": self.outcome_status,
                "outcome_status": self.outcome_status,
                "status_source": self.status_source,
                "cost_usd": 0.0,
                "wall_ms": wall_ms,
            },
            "redaction_key_id": "tier1_default",
        }


_current_trace_context: ContextVar[TraceContext | None] = ContextVar(
    "_current_trace_context", default=None
)


def get_current_trace_context() -> TraceContext | None:
    return _current_trace_context.get()


def get_current_trace() -> dict[str, Any] | None:
    ctx = get_current_trace_context()
    if ctx is None:
        return None
    return ctx.to_ctf_dict()


class trace_agent:
    """Decorator hoặc Context Manager bọc Agent execution."""

    def __init__(
        self,
        name: str = "default_agent",
        version: str = "1.0.0",
        trace_id: str | None = None,
        model_provider: str = "openai",
        model_id: str = "gpt-4o",
    ) -> None:
        self.name: str = name
        self.version: str = version
        self.trace_id: str | None = trace_id
        self.model_provider: str = model_provider
        self.model_id: str = model_id
        self.ctx: TraceContext | None = None
        self._token: Any = None

    def __enter__(self) -> TraceContext:
        self.ctx = TraceContext(
            trace_id=self.trace_id,
            agent_name=self.name,
            agent_version=self.version,
            model_provider=self.model_provider,
            model_id=self.model_id,
        )
        self._token = _current_trace_context.set(self.ctx)
        return self.ctx

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        if exc_val is not None and self.ctx is not None:
            self.ctx.outcome_status = "agent_error"
        if self._token is not None:
            _current_trace_context.reset(self._token)
        return False

    def __call__(self, func: F) -> F:
        agent_name = self.name if self.name != "default_agent" else func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = TraceContext(
                trace_id=self.trace_id,
                agent_name=agent_name,
                agent_version=self.version,
                model_provider=self.model_provider,
                model_id=self.model_id,
            )
            token = _current_trace_context.set(ctx)
            with _tracer.start_as_current_span(f"arc.agent.{agent_name}") as span:
                span.set_attribute("arc.agent.name", agent_name)
                span.set_attribute("arc.trace_id", ctx.trace_id)
                try:
                    res = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return res
                except Exception as exc:
                    ctx.outcome_status = "agent_error"
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)
                    raise
                finally:
                    _current_trace_context.reset(token)

        return cast(F, wrapper)


def trace_tool(
    name: str | Callable[..., Any] | None = None,
    redactor: Redactor | None = None,
    trap_exceptions: bool = True,
) -> Any:
    """Decorator bọc Tool calls.

    Thu thập span, latency, input args (được redact), output/exception,
    và export ra CTF step dict. Bẫy exception mặc định để tránh sập host.
    """
    tool_name_arg: str | None = None
    func_arg: Callable[..., Any] | None = None

    if callable(name):
        func_arg = name
    elif isinstance(name, str):
        tool_name_arg = name

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = tool_name_arg or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_current_trace_context()
            step_id = len(ctx.steps) if ctx is not None else 0
            t_virtual_ms = (
                round((time.perf_counter() - ctx.start_perf) * 1000, 2)
                if ctx is not None
                else 0.0
            )

            sanitized_args: dict[str, Any] = {}
            if args:
                sanitized_args["args"] = redact_payload(list(args))
            if kwargs:
                sanitized_args.update(redact_payload(kwargs))

            t0 = time.perf_counter()

            with _tracer.start_as_current_span(f"arc.tool.{tool_name}") as span:
                span.set_attribute("arc.tool.name", tool_name)

                try:
                    result = func(*args, **kwargs)
                    latency_ms = round((time.perf_counter() - t0) * 1000, 3)

                    sanitized_result = redact_payload(result)

                    step_dict: dict[str, Any] = {
                        "step_id": step_id,
                        "kind": "tool_call",
                        "t_virtual_ms": t_virtual_ms,
                        "parent_step": None,
                        "request": {
                            "tool": tool_name,
                            "args": sanitized_args,
                            "args_ref": None,
                            "idempotency_key": None,
                            "declared_mutating": None,
                            "mutating": None,
                            "scope": None,
                        },
                        "response": {
                            "status": "ok",
                            "body": sanitized_result,
                            "latency_ms": latency_ms,
                        },
                        "outcome": "success",
                        "forkable": True,
                        "fork_reasons": None,
                    }

                    if ctx is not None:
                        ctx.add_step(step_dict)

                    span.set_status(Status(StatusCode.OK))
                    return result

                except Exception as exc:
                    latency_ms = round((time.perf_counter() - t0) * 1000, 3)
                    tb_str = traceback.format_exc()

                    step_dict = {
                        "step_id": step_id,
                        "kind": "tool_call",
                        "t_virtual_ms": t_virtual_ms,
                        "parent_step": None,
                        "request": {
                            "tool": tool_name,
                            "args": sanitized_args,
                            "args_ref": None,
                            "idempotency_key": None,
                            "declared_mutating": None,
                            "mutating": None,
                            "scope": None,
                        },
                        "response": {
                            "status": "error",
                            "error": redact_payload(str(exc)),
                            "traceback": redact_payload(tb_str),
                            "latency_ms": latency_ms,
                        },
                        "outcome": "error",
                        "forkable": False,
                        "fork_reasons": None,
                    }

                    if ctx is not None:
                        ctx.add_step(step_dict)

                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)

                    if trap_exceptions:
                        return {
                            "status": "error",
                            "error": str(exc),
                            "outcome": "error",
                        }
                    raise

        return wrapper

    if func_arg is not None:
        return decorator(func_arg)
    return decorator
