"""Fault Injector Engine for Sandbox Proxy and Fork-Replay execution environments.

Intercepts tool execution steps and injects infrastructure (Group A) or semantic (Group B)
faults without modifying agent source code.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

# Ensure execution/sandbox-runner is discoverable for PassiveEffectLedger
sbx_path = os.path.abspath("execution/sandbox-runner")
if sbx_path not in sys.path:
    sys.path.insert(0, sbx_path)

try:
    from passive_ledger import PassiveEffectLedger, is_mutating_tool
except ImportError:
    try:
        from execution.sandbox_runner.passive_ledger import (  # type: ignore[no-redef]
            PassiveEffectLedger,
            is_mutating_tool,
        )
    except ImportError:

        def is_mutating_tool(tool_name: str) -> bool:  # type: ignore[misc]
            mutating_keywords = {"refund", "issue_refund", "update", "delete", "create", "pay"}
            return any(k in tool_name.lower() for k in mutating_keywords)

        class PassiveEffectLedger:  # type: ignore[no-redef]
            """Fallback stub if sandbox runner package is unlinked."""

            def __init__(self) -> None:
                self.effects: list[dict[str, Any]] = []

            def record_effect(self, tool_name: str, arguments: dict[str, Any], **kw: Any) -> dict[str, Any]:
                entry = {"type": tool_name, "delta": arguments}
                self.effects.append(entry)
                return entry

            def trap_mutating_call(self, tool_name: str, arguments: dict[str, Any], **kw: Any) -> dict[str, Any]:
                self.record_effect(tool_name, arguments)
                return {"status": "ok", "message": f"Trapped {tool_name}"}


try:
    from fault_catalog import FaultCatalog, FaultSpec, FaultType
except ImportError:
    from execution.fork_engine.fault_catalog import (  # type: ignore[no-redef]
        FaultCatalog,
        FaultSpec,
        FaultType,
    )


class FaultInjector:
    """Interceptor Engine executing fault injection specs during sandbox tool invocations."""

    def __init__(
        self,
        catalog: FaultCatalog | Sequence[FaultSpec | dict[str, Any]] | None = None,
        ledger: PassiveEffectLedger | None = None,
    ) -> None:
        if catalog is None:
            self.catalog = FaultCatalog()
        elif isinstance(catalog, FaultCatalog):
            self.catalog = catalog
        else:
            self.catalog = FaultCatalog.from_list(catalog)

        self.ledger = ledger or PassiveEffectLedger()
        self.applied_faults: list[FaultSpec] = []
        self.last_executed_step: int = 0

    @property
    def fault_untriggered(self) -> bool:
        """Returns True if any registered fault specification was not triggered/applied."""
        return len(self.catalog.get_untriggered_faults()) > 0

    def has_untriggered_faults(self) -> bool:
        """Method interface checking whether untriggered faults exist."""
        return self.fault_untriggered

    def get_applied_faults(self) -> list[FaultSpec]:
        """Returns list of fault specifications that were applied during execution."""
        return list(self.applied_faults)

    def intercept_tool_call(
        self,
        step_id: int,
        tool_name: str,
        args: dict[str, Any],
        default_executor: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Intercepts a tool invocation at a specific step_id and applies matching fault spec.

        If no fault spec applies, proceeds with normal tool execution or passive ledger trapping.
        """
        self.last_executed_step = max(self.last_executed_step, step_id)

        # Check for unapplied matching faults for this step and tool
        matching_faults = self.catalog.get_faults_for_step(step_id=step_id, tool_name=tool_name)

        if not matching_faults:
            # Normal execution path
            return self._execute_normal(tool_name, args, step_id, default_executor)

        # Apply the first matching fault spec
        spec = matching_faults[0]
        spec.applied = True
        self.applied_faults.append(spec)

        return self._apply_fault(spec, step_id, tool_name, args, default_executor)

    def _execute_normal(
        self,
        tool_name: str,
        args: dict[str, Any],
        step_id: int,
        default_executor: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Executes standard tool call or traps in PassiveEffectLedger if mutating."""
        if default_executor is not None:
            res = default_executor(tool_name, args)
            if isinstance(res, dict):
                typed_res: dict[str, Any] = {str(k): v for k, v in res.items()}
                return typed_res  # type: ignore[no-any-return]
            return {"status": "ok", "result": res}

        if is_mutating_tool(tool_name):
            return self.ledger.trap_mutating_call(tool_name, args, step_id=step_id)  # type: ignore[no-any-return]

        return {
            "status": "ok",
            "tool_name": tool_name,
            "result": f"Tool '{tool_name}' executed normally",
        }

    def _apply_fault(
        self,
        spec: FaultSpec,
        step_id: int,
        tool_name: str,
        args: dict[str, Any],
        default_executor: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Applies infrastructure or semantic fault injection logic."""
        fault_type = spec.fault_type
        params = spec.params

        # ── Group A: Infrastructure Faults ─────────────────────────────────────
        if fault_type == FaultType.TIMEOUT_BEFORE_COMMIT.value:
            # Crucial: NO effect recorded in ledger
            latency_ms = params.get("latency_ms", 0)
            if latency_ms > 0:
                time.sleep(latency_ms / 1000.0)
            return {
                "status_code": 504,
                "error": "Gateway Timeout",
                "detail": "504 Gateway Timeout (timeout_before_commit injected)",
                "fault": fault_type,
            }

        if fault_type == FaultType.TIMEOUT_AFTER_COMMIT.value:
            # Crucial: Effect IS recorded in ledger FIRST
            self.ledger.record_effect(
                tool_name=tool_name,
                arguments=args,
                step_id=step_id,
            )
            latency_ms = params.get("latency_ms", 0)
            if latency_ms > 0:
                time.sleep(latency_ms / 1000.0)
            return {
                "status_code": 504,
                "error": "Gateway Timeout",
                "detail": "504 Gateway Timeout (timeout_after_commit injected)",
                "fault": fault_type,
            }

        if fault_type == FaultType.HTTP_500.value:
            return {
                "status_code": 500,
                "error": "Internal Server Error",
                "detail": "500 Internal Server Error injected",
                "fault": fault_type,
            }

        if fault_type == FaultType.HTTP_502.value:
            return {
                "status_code": 502,
                "error": "Bad Gateway",
                "detail": "502 Bad Gateway injected",
                "fault": fault_type,
            }

        if fault_type == FaultType.HTTP_429.value:
            return {
                "status_code": 429,
                "error": "Too Many Requests",
                "detail": "429 Too Many Requests injected",
                "fault": fault_type,
            }

        if fault_type == FaultType.LATENCY_SPIKE.value:
            delay_ms = params.get("delay_ms", params.get("latency_ms", 1000))
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            return self._execute_normal(tool_name, args, step_id, default_executor)

        # ── Group B: Semantic Faults ───────────────────────────────────────────
        # Get baseline response
        base_response = self._get_baseline_response(tool_name, args, step_id, default_executor)

        if fault_type == FaultType.REQUIRED_FIELD_NULL.value:
            target_field = params.get("field") or params.get("null_field") or "order_id"
            res = dict(base_response)
            res[target_field] = None
            return res

        if fault_type == FaultType.BAD_SCHEMA.value:
            # Corrupt payload structure
            if "invalid_payload" in params and isinstance(params["invalid_payload"], dict):
                invalid_payload: dict[str, Any] = {
                    str(k): v for k, v in params["invalid_payload"].items()
                }
                return invalid_payload
            res = dict(base_response)
            res.pop("status", None)
            res["__malformed_schema_error__"] = True
            return res

        if fault_type == FaultType.EMPTY_LIST.value:
            target_field = params.get("field", "items")
            res = dict(base_response)
            res[target_field] = []
            return res

        if fault_type == FaultType.TYPE_COERCION.value:
            target_field = params.get("field")
            res = dict(base_response)
            if target_field and target_field in res:
                res[target_field] = str(res[target_field])
            return res

        if fault_type == FaultType.BOUNDARY_VALUE.value:
            target_field = params.get("field", "amount")
            boundary_val = params.get("value", 0)
            res = dict(base_response)
            res[target_field] = boundary_val
            return res

        # Default fallback
        return self._execute_normal(tool_name, args, step_id, default_executor)

    def _get_baseline_response(
        self,
        tool_name: str,
        args: dict[str, Any],
        step_id: int,
        default_executor: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Fetches standard response from default_executor or mock dictionary."""
        if default_executor is not None:
            res = default_executor(tool_name, args)
            if isinstance(res, dict):
                typed_res: dict[str, Any] = {str(k): v for k, v in res.items()}
                return typed_res  # type: ignore[no-any-return]
            return {"status": "active", "result": res}

        if tool_name == "lookup_order":
            order_id = args.get("order_id", "ORD-12345")
            return {"order_id": order_id, "status": "active"}

        return {"status": "ok", "tool_name": tool_name, "data": args}
