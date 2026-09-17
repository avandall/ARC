"""FastAPI Router for Approval Gateway & Catalog Sync Endpoints (TASK-P3-004)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from approval_gateway.gateway import ApprovalGateway

router = APIRouter(prefix="/v1", tags=["approval-gateway"])

_gateway_instance = ApprovalGateway()


def get_gateway() -> ApprovalGateway:
    return _gateway_instance


class RejectCandidateRequest(BaseModel):
    reason: str = Field(..., description="Reason for candidate rejection")
    rejected_by: str = Field(default="engineer", description="User or service performing rejection")
    statement: str | None = Field(default=None, description="Candidate statement if not in DB")


class CatalogSyncRequest(BaseModel):
    direction: str = Field(default="yaml_to_db", description="Sync direction (yaml_to_db or db_to_yaml)")
    reverse: bool = Field(default=False, description="Attempt reverse sync from DB to YAML")


@router.post(
    "/mining/candidates/{candidate_id}/reject",
    status_code=status.HTTP_200_OK,
)
def reject_candidate_endpoint(
    candidate_id: str,
    req: RejectCandidateRequest,
    gateway: ApprovalGateway = Depends(get_gateway),  # noqa: B008
) -> dict[str, Any]:
    """Rejects a candidate and records its normalized SHA-256 statement hash in rejected_candidates."""
    try:
        res = gateway.reject_candidate(
            candidate_id=candidate_id,
            reason=req.reason,
            rejected_by=req.rejected_by,
            candidate_statement=req.statement,
        )
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post(
    "/catalog/sync",
    status_code=status.HTTP_200_OK,
)
def sync_catalog_endpoint(
    req: CatalogSyncRequest | None = None,
    gateway: ApprovalGateway = Depends(get_gateway),  # noqa: B008
) -> dict[str, Any]:
    """Syncs Property Catalog from repo YAML into DB cache, rejecting DB to YAML auto-sync."""
    direction = req.direction if req else "yaml_to_db"
    reverse = req.reverse if req else False
    try:
        res = gateway.sync_catalog(direction=direction, reverse=reverse)
        return res
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
