"""MockDatabase tool model plugin implementation (§3.3, §7.4)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from arc.execution.tool_models.base import ToolModel, UnsupportedFaultException, register

SUPPORTED_DB_FAULTS: set[str] = {
    "timeout_before_commit",
    "timeout_after_commit",
    "http_500",
    "database_error",
    "duplicate_action",
    "concurrent_write",
    "partial_success",
    "bad_schema",
}


@register
class MockDatabase(ToolModel):
    """Tool model simulating an isolated relational database engine.

    Maintains in-memory table records, mutation history, and effect ledger entries.
    """

    tool_name: str = "database_query"
    version: str = "1.0.0"

    def __init__(
        self,
        tables: dict[str, list[dict[str, Any]]] | None = None,
        effects: list[dict[str, Any]] | None = None,
        step_counter: int = 0,
    ) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = (
            copy.deepcopy(tables)
            if tables is not None
            else {
                "orders": [
                    {"id": "8842", "status": "completed", "total_cents": 4599, "customer_id": "cust_404"}
                ],
                "customers": [
                    {"id": "cust_404", "name": "Jane Doe", "balance": 0}
                ],
            }
        )
        self.effects: list[dict[str, Any]] = (
            copy.deepcopy(effects) if effects is not None else []
        )
        self.step_counter: int = step_counter

    def clone_fresh_state(self, seed_state_ref: str = "") -> MockDatabase:
        """Clones a fresh independent instance with deep-copied state."""
        return MockDatabase(
            tables=copy.deepcopy(self.tables),
            effects=copy.deepcopy(self.effects),
            step_counter=self.step_counter,
        )

    def handle(
        self,
        request_args: dict[str, Any],
        injected_fault: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handles a database query/mutation, validating faults and recording side effects."""
        if injected_fault:
            fault_type = str(
                injected_fault.get("type") or injected_fault.get("fault_type") or ""
            )
            if fault_type and fault_type not in SUPPORTED_DB_FAULTS:
                raise UnsupportedFaultException(
                    f"MockDatabase rejects unsupported fault type '{fault_type}'. "
                    f"Supported types are: {sorted(SUPPORTED_DB_FAULTS)}"
                )

        query = str(request_args.get("query") or request_args.get("sql") or "").strip()
        table_name = str(request_args.get("table", "orders"))
        action = str(request_args.get("action", "select")).lower()

        # Check for mutation actions
        is_mutation = any(
            verb in query.upper() for verb in ["INSERT", "UPDATE", "DELETE", "DROP"]
        ) or action in ("insert", "update", "delete")

        self.step_counter += 1

        if is_mutation:
            effect_id = f"eff_db_{uuid.uuid4().hex[:8]}"
            effect_entry = {
                "effect_id": effect_id,
                "step_id": self.step_counter,
                "type": "database.mutation",
                "resource": f"table:{table_name}",
                "delta": {
                    "action": action,
                    "query": query,
                    "affected_rows": 1,
                },
                "reversible": True,
                "observed_at_step": self.step_counter,
            }
            self.effects.append(effect_entry)

            return {
                "status": "ok",
                "affected_rows": 1,
                "effect_id": effect_id,
                "action": action,
            }

        # Read query
        rows = self.tables.get(table_name, [])
        return {
            "status": "ok",
            "rows": rows,
            "count": len(rows),
        }

    def to_effect_ledger_entries(self) -> list[dict[str, Any]]:
        """Exports accumulated effect entries conforming to schema §4.3."""
        return copy.deepcopy(self.effects)
