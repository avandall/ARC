"""MockPaymentGateway tool model plugin implementation (§3.3, §7.4)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from arc.execution.tool_models.base import ToolModel, UnsupportedFaultException, register

SUPPORTED_FAULTS: set[str] = {
    "timeout_before_commit",
    "timeout_after_commit",
    "http_500",
    "http_502",
    "http_429",
    "latency_spike",
    "bad_schema",
    "required_field_null",
    "empty_list",
    "type_coercion",
    "boundary_value",
}


@register
class MockPaymentGateway(ToolModel):
    """Tool model simulating a payment gateway refund operation (§3.3).

    Maintains isolated balances, idempotency key cache, and effect ledger entries.
    """

    tool_name: str = "issue_refund"
    version: str = "1.0.0"

    def __init__(
        self,
        balances: dict[str, float] | None = None,
        processed_transactions: dict[str, dict[str, Any]] | None = None,
        effects: list[dict[str, Any]] | None = None,
        step_counter: int = 0,
    ) -> None:
        """Initializes state for MockPaymentGateway."""
        self.balances: dict[str, float] = (
            dict(balances) if balances is not None else {"order:8842": 100.0}
        )
        self.processed_transactions: dict[str, dict[str, Any]] = (
            copy.deepcopy(processed_transactions) if processed_transactions is not None else {}
        )
        self.effects: list[dict[str, Any]] = (
            copy.deepcopy(effects) if effects is not None else []
        )
        self.step_counter: int = step_counter

    def clone_fresh_state(self, seed_state_ref: str = "") -> MockPaymentGateway:
        """Clones a fresh independent instance with deep-copied state (§7.4).

        Args:
            seed_state_ref: Optional state snapshot reference ID.

        Returns:
            A new MockPaymentGateway instance with isolated state.
        """
        return MockPaymentGateway(
            balances=copy.deepcopy(self.balances),
            processed_transactions=copy.deepcopy(self.processed_transactions),
            effects=copy.deepcopy(self.effects),
            step_counter=self.step_counter,
        )

    def handle(
        self,
        request_args: dict[str, Any],
        injected_fault: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handles refund request, verifying idempotency and injected fault specs.

        Args:
            request_args: Payload containing order_id, amount, idempotency_key, etc.
            injected_fault: Optional fault specification dict.

        Returns:
            Mock payment response dict.

        Raises:
            UnsupportedFaultException: If injected_fault specifies an unknown fault type.
        """
        # 1. Fault validation
        if injected_fault:
            fault_type = str(
                injected_fault.get("type") or injected_fault.get("fault_type") or ""
            )
            if fault_type and fault_type not in SUPPORTED_FAULTS:
                raise UnsupportedFaultException(
                    f"MockPaymentGateway rejects unsupported fault type '{fault_type}'. "
                    f"Supported fault types are: {sorted(SUPPORTED_FAULTS)}"
                )

        # 2. Extract key parameters
        idempotency_key = request_args.get("idempotency_key") or request_args.get("idem_key")
        raw_order_id = str(request_args.get("order_id", "8842"))
        resource = raw_order_id if raw_order_id.startswith("order:") else f"order:{raw_order_id}"

        # 3. Idempotency Check
        if idempotency_key and str(idempotency_key) in self.processed_transactions:
            return self.processed_transactions[str(idempotency_key)]

        # 4. Process new refund
        amount = float(request_args.get("amount", 0.0))
        currency = str(request_args.get("currency", "USD"))

        if resource not in self.balances:
            self.balances[resource] = 100.0

        self.balances[resource] -= amount
        self.step_counter += 1

        # 5. Record effect ledger entry conforming to schema §4.3
        effect_id = f"eff_{uuid.uuid4().hex[:8]}"
        effect_entry: dict[str, Any] = {
            "effect_id": effect_id,
            "step_id": self.step_counter,
            "type": "financial.refund",
            "resource": resource,
            "delta": {
                "amount": -abs(amount),
                "amount_cents": -round(abs(amount) * 100),
                "currency": currency,
            },
            "reversible": False,
            "idempotency_key": str(idempotency_key) if idempotency_key else None,
            "idem_key": str(idempotency_key) if idempotency_key else None,
            "observed_at_step": self.step_counter,
        }
        self.effects.append(effect_entry)

        # 6. Formulate response
        response: dict[str, Any] = {
            "status": "ok",
            "refund_id": f"ref_{uuid.uuid4().hex[:8]}",
            "order_id": raw_order_id,
            "amount": amount,
            "currency": currency,
            "idempotency_key": idempotency_key,
            "remaining_balance": self.balances[resource],
        }

        if idempotency_key:
            self.processed_transactions[str(idempotency_key)] = response

        return response

    def to_effect_ledger_entries(self) -> list[dict[str, Any]]:
        """Exports accumulated effect entries conforming to schema §4.3.

        Returns:
            List of effect dictionaries.
        """
        return copy.deepcopy(self.effects)
