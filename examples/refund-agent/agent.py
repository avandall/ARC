"""Reference Implementation: `refund-agent` (§19).

Demonstrates an end-to-end e-commerce order refund agent for Order #8842.
Captured with `arc_sdk` decorators (`@trace_agent`, `@trace_tool`), showcasing both nominal
execution and double-refund invariant violation (`INV-PAY-002`) under `timeout_after_commit` fault injection.
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

# Ensure sdk/python is in sys.path
_sdk_python_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "python")
)
if _sdk_python_dir not in sys.path:
    sys.path.insert(0, _sdk_python_dir)

from arc_sdk.interceptor import get_current_trace_context, trace_agent, trace_tool

# Invariant specification for INV-PAY-002
INV_PAY_002_SPEC: dict[str, Any] = {
    "id": "INV-PAY-002",
    "statement": "Tổng các effect financial.refund cho một order không vượt quá giá trị order",
    "category": "conservation",
    "severity": "critical",
    "check": "sum([abs(e.delta.amount_cents) for e in effects if e.type == 'financial.refund']) <= order.total_cents",
}


# ── Step Tools ─────────────────────────────────────────────────────────────────


@trace_tool(name="lookup")
def lookup(order_id: str) -> dict[str, Any]:
    """Tool 1: Looks up order details from database."""
    clean_id = str(order_id).replace("order:", "")
    return {
        "order_id": clean_id,
        "customer_id": "cust_404",
        "total_amount": 45.99,
        "currency": "USD",
        "status": "delivered",
        "item": "Wireless Headphones",
    }


@trace_tool(name="check_policy")
def check_policy(order_id: str) -> dict[str, Any]:
    """Tool 2: Checks refund policy eligibility for an order."""
    clean_id = str(order_id).replace("order:", "")
    return {
        "order_id": clean_id,
        "eligible": True,
        "max_refund_amount": 45.99,
        "policy_code": "POL-REFUND-30D",
    }


@trace_tool(name="issue_refund")
def issue_refund(
    order_id: str,
    amount: float,
    idempotency_key: str | None = None,
    fault_spec: dict[str, Any] | None = None,
    effects_ledger: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tool 3: Issues a payment gateway refund.

    Simulates commit and optional fault injection (`timeout_after_commit`).
    """
    clean_id = str(order_id).replace("order:", "")
    resource = f"order:{clean_id}"
    amount_cents = round(amount * 100)

    # 1. Record passive effect ledger entry
    effect_id = f"eff_{uuid.uuid4().hex[:8]}"
    effect_entry: dict[str, Any] = {
        "effect_id": effect_id,
        "step_id": 2,
        "type": "financial.refund",
        "resource": resource,
        "delta": {
            "amount": -abs(amount),
            "amount_cents": -abs(amount_cents),
            "currency": "USD",
        },
        "reversible": False,
        "idempotency_key": idempotency_key,
        "observed_at_step": 2,
    }

    if effects_ledger is not None:
        effects_ledger.append(effect_entry)

    # Context update if within active trace context
    ctx = get_current_trace_context()
    if ctx is not None:
        ctx.effects.append(effect_entry)

    # 2. Check for timeout_after_commit fault injection
    if fault_spec:
        fault_type = fault_spec.get("type") or fault_spec.get("fault_type")
        if fault_type == "timeout_after_commit":
            # Gateway committed effect, but connection timed out back to agent
            return {
                "status_code": 504,
                "status": "error",
                "error": "504 Gateway Timeout (timeout_after_commit)",
            }

    return {
        "status": "ok",
        "refund_id": f"ref_{uuid.uuid4().hex[:8]}",
        "order_id": clean_id,
        "amount": amount,
        "idempotency_key": idempotency_key,
    }


@trace_tool(name="send_email")
def send_email(customer_id: str, message: str) -> dict[str, Any]:
    """Tool 4: Sends customer confirmation email."""
    return {
        "status": "sent",
        "customer_id": customer_id,
        "message": message,
    }


# ── Workflow Execution ────────────────────────────────────────────────────────


@trace_agent(name="refund-agent", version="1.0.0")
def run_refund_agent(
    order_id: str = "8842",
    inject_fault: bool = False,
    fault_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Executes the full refund agent workflow: lookup -> check_policy -> issue_refund -> send_email.

    If `inject_fault` is True, injects `timeout_after_commit` fault during `issue_refund`.
    Because the agent lacks idempotency key handling, it retries `issue_refund`, leading to a double refund.
    """
    ctx = get_current_trace_context()
    effects: list[dict[str, Any]] = []

    # 1. Lookup order details
    order_info = lookup(order_id)

    # 2. Check policy eligibility
    policy_info = check_policy(order_id)

    if not policy_info.get("eligible"):
        return {"status": "rejected", "reason": "Ineligible for refund"}

    # 3. Issue refund
    amount = float(order_info["total_amount"])
    active_fault = fault_spec or (
        {"type": "timeout_after_commit", "step": 2, "tool": "issue_refund"}
        if inject_fault
        else None
    )

    refund_res = issue_refund(
        order_id=order_id,
        amount=amount,
        idempotency_key=None,  # Vulnerability: missing idempotency key!
        fault_spec=active_fault,
        effects_ledger=effects,
    )

    # Agent error handling: retry issue_refund if timeout occurred
    if refund_res.get("status_code") == 504 or refund_res.get("status") == "error":
        # Retry without idempotency key protection -> Double refund!
        refund_res = issue_refund(
            order_id=order_id,
            amount=amount,
            idempotency_key=None,
            fault_spec=None,  # Second call succeeds
            effects_ledger=effects,
        )

    # 4. Send confirmation email
    email_res = send_email(
        customer_id=order_info["customer_id"],
        message=f"Your refund of ${amount:.2f} for Order #{order_id} has been processed.",
    )

    ctf_dict = ctx.to_ctf_dict() if ctx is not None else {}
    if ctx is not None and effects and not ctf_dict.get("effects"):
        ctf_dict["effects"] = effects

    return {
        "status": "completed",
        "order_id": order_id,
        "amount_refunded": amount,
        "lookup": order_info,
        "policy": policy_info,
        "refund": refund_res,
        "email": email_res,
        "ctf_trace": ctf_dict,
        "effects": ctf_dict.get("effects", effects),
    }


if __name__ == "__main__":
    print("Executing Nominal refund-agent workflow...")
    res_nominal = run_refund_agent(order_id="8842", inject_fault=False)
    print(f"Nominal Status: {res_nominal['status']}")
    print(f"Effects count: {len(res_nominal['effects'])}")

    print("\nExecuting Chaos refund-agent workflow (timeout_after_commit)...")
    res_chaos = run_refund_agent(order_id="8842", inject_fault=True)
    print(f"Chaos Status: {res_chaos['status']}")
    print(f"Effects count: {len(res_chaos['effects'])}")
