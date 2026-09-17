"""Collector REST API FastAPI Application.

Endpoints:
- POST /v1/collector/traces
- GET  /v1/traces
- GET  /v1/traces/{trace_id}
- GET  /v1/traces/{trace_id}/bundle
"""

import os
import sys
from typing import Any

# Ensure control-plane directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from approval_gateway.routes import router as approval_router
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from warehouse.warehouse import TraceWarehouse

from collector.auth import verify_token
from collector.routes import router as bundle_router

app = FastAPI(title="ARC+ Control Plane Collector REST API", version="1.0.0")

warehouse = TraceWarehouse()


def get_warehouse() -> TraceWarehouse:
    return warehouse


app.include_router(bundle_router)
app.include_router(approval_router)


@app.post(
    "/v1/collector/traces",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_token)],
)
def post_collector_traces(
    payload: dict[str, Any],
    response: Response,
    wh: TraceWarehouse = Depends(get_warehouse),  # noqa: B008
) -> dict[str, str]:
    """Ingests CTF v1.0 trace payload, stores metadata in Postgres and payload blobs in S3."""
    if "trace_id" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required field: trace_id",
        )

    trace_id = wh.save_trace(payload)
    response.status_code = status.HTTP_202_ACCEPTED
    return {"status": "accepted", "trace_id": trace_id}


@app.get(
    "/v1/traces",
    dependencies=[Depends(verify_token)],
)
def get_traces(
    agent: str | None = Query(None, alias="agent"),
    agent_name: str | None = Query(None, alias="agent_name"),
    outcome_status: str | None = Query(None),
    since: str | None = Query(None),
    x_allowed_agents: str | None = Header(None, alias="X-Allowed-Agents"),
    wh: TraceWarehouse = Depends(get_warehouse),  # noqa: B008
) -> list[dict[str, Any]]:
    """Retrieves trace summaries matching filters and RLS policy."""
    target_agent = agent or agent_name
    wh.set_rls_context(x_allowed_agents)
    return wh.list_traces(agent=target_agent, outcome_status=outcome_status, since=since)


@app.get(
    "/v1/traces/{trace_id}",
    dependencies=[Depends(verify_token)],
)
def get_trace_by_id(
    trace_id: str,
    x_allowed_agents: str | None = Header(None, alias="X-Allowed-Agents"),
    wh: TraceWarehouse = Depends(get_warehouse),  # noqa: B008
) -> dict[str, Any]:
    """Reconstructs full CTF v1.0 trace from PostgreSQL/SQLite metadata and S3 payload blobs."""
    wh.set_rls_context(x_allowed_agents)
    ctf_trace = wh.get_trace(trace_id)
    if not ctf_trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace with ID '{trace_id}' not found",
        )
    return ctf_trace
