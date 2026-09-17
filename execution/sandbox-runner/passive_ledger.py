"""Passive Effect Ledger for Phase 1 Replay.

Traps mutating tool calls in memory, returning mock OK responses without side-effects,
and records effect deltas per schema §4.3 (schemas/json/effect_v1.json).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

MUTATING_KEYWORDS: set[str] = {
    "issue_refund",
    "refund",
    "delete",
    "update",
    "create",
    "cancel",
    "transfer",
    "pay",
    "charge",
    "post",
    "write",
    "execute",
}


def is_mutating_tool(tool_name: str) -> bool:
    """Checks whether a tool is mutating based on tool name or action prefix."""
    lower_name = tool_name.lower()
    if lower_name in MUTATING_KEYWORDS:
        return True
    return any(keyword in lower_name for keyword in MUTATING_KEYWORDS)


class PassiveEffectLedger:
    """In-memory Passive Effect Ledger recording mutating tool call deltas."""

    def __init__(self) -> None:
        self.effects: list[dict[str, Any]] = []
        self._step_counter: int = 0

    def record_effect(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        step_id: int | None = None,
        resource: str | None = None,
        effect_type: str | None = None,
        delta: dict[str, Any] | None = None,
        reversible: bool = True,
        idempotency_key: str | None = None,
        observed_at_step: int | None = None,
    ) -> dict[str, Any]:
        """Records an effect entry adhering to schema §4.3 (schemas/json/effect_v1.json)."""
        self._step_counter += 1
        current_step = step_id if step_id is not None else self._step_counter

        # Derive resource identifier if not specified
        if resource is None:
            if "order_id" in arguments:
                resource = f"order:{arguments['order_id']}"
            elif "user_id" in arguments:
                resource = f"user:{arguments['user_id']}"
            elif "account_id" in arguments:
                resource = f"account:{arguments['account_id']}"
            elif "resource" in arguments:
                resource = str(arguments["resource"])
            else:
                resource = f"resource:{tool_name}"

        # Derive delta payload
        effect_delta = delta if delta is not None else dict(arguments)

        # Derive idempotency key
        raw_idem_key = idempotency_key or arguments.get("idempotency_key") or arguments.get("idem_key")
        idem_key = str(raw_idem_key) if raw_idem_key is not None else None

        entry: dict[str, Any] = {
            "effect_id": f"eff_{uuid.uuid4().hex[:8]}",
            "step_id": current_step,
            "type": effect_type or tool_name,
            "resource": resource,
            "delta": effect_delta,
            "reversible": reversible,
            "idempotency_key": idem_key,
            "idem_key": idem_key,
            "observed_at_step": observed_at_step if observed_at_step is not None else current_step,
        }

        self.effects.append(entry)
        return entry

    def trap_mutating_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        mock_response: dict[str, Any] | None = None,
        step_id: int | None = None,
    ) -> dict[str, Any]:
        """Traps a mutating tool call, records effect in ledger, and returns mock response."""
        recorded_entry = self.record_effect(
            tool_name=tool_name,
            arguments=arguments,
            step_id=step_id,
        )

        if mock_response is not None:
            return mock_response

        # Default synthetic mock OK response
        return {
            "status": "ok",
            "message": f"Mutating call '{tool_name}' trapped passively by PassiveEffectLedger",
            "effect_id": recorded_entry["effect_id"],
            "recorded": True,
        }

    def get_effects(self) -> list[dict[str, Any]]:
        """Returns list of recorded effects."""
        return list(self.effects)

    def to_json(self) -> str:
        """Serializes recorded effects into JSON string."""
        return json.dumps(self.effects, indent=2)

    def clear(self) -> None:
        """Clears recorded effects."""
        self.effects.clear()
        self._step_counter = 0
