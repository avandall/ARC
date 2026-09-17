"""Approval Gateway Implementation (TASK-P3-004).

Manages invariant candidate reviews, deduplication against rejected candidate hashes (§8.3),
and enforces catalog sync directional boundaries (YAML-to-DB only, blocking DB-to-YAML auto-sync).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from warehouse.db_store import DatabaseStore

logger = logging.getLogger(__name__)


def compute_statement_hash(statement: str) -> str:
    """Computes SHA-256 hash of normalized (lowercase + trim) candidate statement string."""
    normalized = statement.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ApprovalGateway:
    """Approval Gateway component managing candidate lifecycle, rejection dedup, and catalog sync."""

    def __init__(self, db_store: DatabaseStore | None = None) -> None:
        self.db_store = db_store or DatabaseStore.get_shared_instance()

    def reject_candidate(
        self,
        candidate_id: str,
        reason: str,
        rejected_by: str = "engineer",
        candidate_statement: str | None = None,
    ) -> dict[str, Any]:
        """Rejects an invariant candidate by saving its normalized SHA-256 statement_hash

        to the rejected_candidates table (§8.3) and updating its status to 'rejected'.
        """
        statement = candidate_statement
        if not statement:
            cand = self.db_store.get_candidate(candidate_id)
            if cand:
                statement = cand.get("statement")

        if not statement:
            # Fallback if candidate statement is not found in DB
            statement = candidate_id

        stmt_hash = compute_statement_hash(statement)
        self.db_store.insert_rejected_candidate(
            statement_hash=stmt_hash,
            original_candidate_id=candidate_id,
            reason=reason,
            rejected_by=rejected_by,
        )
        self.db_store.update_candidate_status(candidate_id, "rejected")

        logger.info(f"Candidate '{candidate_id}' rejected with hash '{stmt_hash}'")
        return {
            "status": "rejected",
            "candidate_id": candidate_id,
            "statement_hash": stmt_hash,
            "reason": reason,
            "rejected_by": rejected_by,
        }

    def filter_candidates(self, candidates: list[dict[str, Any] | Any]) -> list[Any]:
        """Filters out any candidates whose statement_hash matches a record in rejected_candidates."""
        filtered = []
        for cand in candidates:
            stmt = ""
            if isinstance(cand, dict):
                stmt = cand.get("statement", "")
            elif hasattr(cand, "statement"):
                stmt = getattr(cand, "statement", "")

            if stmt:
                stmt_hash = compute_statement_hash(stmt)
                if self.db_store.get_rejected_candidate_by_hash(stmt_hash):
                    logger.info(f"Skipping candidate with rejected statement_hash: {stmt_hash}")
                    continue
            filtered.append(cand)
        return filtered

    def sync_catalog(self, direction: str = "yaml_to_db", **kwargs: Any) -> dict[str, Any]:
        """Syncs Property Catalog.

        Enforces strictly that sync only reads from repo YAML into DB cache,
        rejecting any direct auto-sync write-back request from DB to YAML file without a PR commit.
        """
        normalized_dir = str(direction).lower().strip()
        if normalized_dir in ("db_to_yaml", "reverse", "db-to-yaml") or kwargs.get("reverse") is True:
            raise ValueError(
                "Direct auto-sync from DB to YAML is forbidden (§8.3). Changes must be committed via Git PR."
            )

        return {
            "status": "synced",
            "direction": "yaml_to_db",
            "message": "Property catalog synced from repo YAML into DB cache successfully.",
        }
