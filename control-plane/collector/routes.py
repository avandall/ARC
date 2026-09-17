"""Collector API extra routes for HarnessBundle generation."""

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from warehouse.bundle_generator import HarnessBundleGenerator
from warehouse.warehouse import TraceWarehouse

from collector.auth import verify_token

router = APIRouter(prefix="/v1", tags=["bundles"])


def get_warehouse() -> TraceWarehouse:
    from collector.main import warehouse

    return warehouse


@router.get(
    "/traces/{trace_id}/bundle",
    dependencies=[Depends(verify_token)],
)
def get_trace_bundle(
    trace_id: str,
    secret_key: str | None = Query(None, alias="secret_key"),
    x_hmac_secret_key: str | None = Header(None, alias="X-HMAC-Secret-Key"),
    x_allowed_agents: str | None = Header(None, alias="X-Allowed-Agents"),
    wh: TraceWarehouse = Depends(get_warehouse),  # noqa: B008
) -> dict[str, Any]:
    """Generates a signed, standalone HarnessBundle v1.0 payload for a trace."""
    wh.set_rls_context(x_allowed_agents)
    ctf_trace = wh.get_trace(trace_id)
    if not ctf_trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace with ID '{trace_id}' not found",
        )

    hmac_key = (
        secret_key
        or x_hmac_secret_key
        or os.environ.get("ARC_HMAC_SECRET_KEY", "super-secret-hmac-key")
    )
    bundle = HarnessBundleGenerator.generate(ctf_trace, secret_key=hmac_key)
    return bundle
