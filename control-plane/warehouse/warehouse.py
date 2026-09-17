"""Trace Warehouse module.

Unites PostgreSQL/SQLite metadata DB and S3 content-addressed blob store to save and
reconstruct CTF v1.0 traces.
"""

import json
from typing import Any

from .blob_store import S3BlobStore
from .db_store import DatabaseStore


class TraceWarehouse:
    """Facade for trace ingestion, blob hashing/storage, querying, and CTF v1.0 reconstruction."""

    def __init__(
        self,
        db_store: DatabaseStore | None = None,
        blob_store: S3BlobStore | None = None,
    ) -> None:
        self.db = db_store or DatabaseStore()
        self.blob = blob_store or S3BlobStore()

    def set_rls_context(self, allowed_agents: str | None) -> None:
        """Sets RLS policy allowed agents for the active session context."""
        self.db.set_allowed_agents(allowed_agents)

    def _ensure_blob_ref(self, val: Any) -> str | None:
        if val is None:
            return None
        if isinstance(val, str) and val.startswith("sha256:"):
            # Ensure blob store retains this reference if payload is passed directly
            return val
        return self.blob.put(val)

    def save_trace(self, ctf_data: dict[str, Any]) -> str:
        """Ingests a CTF v1.0 trace dictionary.

        Hashes payload blobs with SHA-256 to S3/MinIO and stores metadata into Postgres/SQLite.
        """
        trace_id = str(ctf_data["trace_id"])
        agent = ctf_data.get("agent", {})
        model = ctf_data.get("model", {})
        params = model.get("params") or {}
        outcome = ctf_data.get("outcome", {})

        # Handle final state ref blob
        final_state = ctf_data.get("final_state_ref")
        final_state_ref = self._ensure_blob_ref(final_state) if final_state else None

        trace_meta = {
            "trace_id": trace_id,
            "session_id": ctf_data.get("session_id"),
            "agent_name": agent.get("name", "unknown"),
            "agent_version": agent.get("version", "1.0.0"),
            "git_sha": agent.get("git_sha"),
            "model_provider": model.get("provider", "unknown"),
            "model_id": model.get("model_id", "unknown"),
            "temperature": params.get("temperature", 0.0),
            "seed": params.get("seed"),
            "determinism_lvl": ctf_data.get("determinism_level", "L2"),
            "outcome_status": outcome.get("status") or outcome.get("outcome_status", "unknown"),
            "status_source": outcome.get("status_source", "agent_self_report"),
            "cost_usd": outcome.get("cost_usd"),
            "wall_ms": outcome.get("wall_ms"),
            "redaction_key_id": ctf_data.get("redaction_key_id", "default"),
            "final_state_ref": final_state_ref,
        }

        steps_meta = []
        for s in ctf_data.get("steps", []):
            req = s.get("request") or {}
            resp = s.get("response") or {}

            # Parse or store args
            args_val = req.get("args_ref") or req.get("args")
            args_ref = self._ensure_blob_ref(args_val)

            # Parse or store body
            body_val = resp.get("body_ref") or resp.get("body")
            body_ref = self._ensure_blob_ref(body_val)

            # Parse or store state snapshot
            state_val = s.get("state_snapshot_ref") or s.get("state_snapshot")
            state_snapshot_ref = self._ensure_blob_ref(state_val)

            steps_meta.append(
                {
                    "step_id": s["step_id"],
                    "kind": s["kind"],
                    "t_virtual_ms": s.get("t_virtual_ms", 0),
                    "parent_step": s.get("parent_step"),
                    "tool_name": req.get("tool"),
                    "args_ref": args_ref,
                    "body_ref": body_ref,
                    "idempotency_key": req.get("idempotency_key"),
                    "mutating": req.get("mutating") or req.get("declared_mutating", False),
                    "forkable": s.get("forkable", False),
                    "fork_reasons": s.get("fork_reasons", []),
                    "state_snapshot_ref": state_snapshot_ref,
                }
            )

        effects_meta = []
        for e in ctf_data.get("effects", []):
            effects_meta.append(
                {
                    "effect_id": e["effect_id"],
                    "step_id": e["step_id"],
                    "type": e["type"],
                    "resource": e["resource"],
                    "delta": e.get("delta"),
                    "reversible": e.get("reversible", False),
                    "idem_key": e.get("idem_key") or e.get("idempotency_key"),
                    "observed_at_step": e.get("observed_at_step", e["step_id"]),
                }
            )

        self.db.insert_trace(trace_meta, steps_meta, effects_meta)
        return trace_id

    def list_traces(
        self,
        agent: str | None = None,
        outcome_status: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Queries traces matching filters and RLS policies."""
        return self.db.get_traces(agent=agent, outcome_status=outcome_status, since=since)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Reconstructs full CTF v1.0 trace by merging Postgres/SQLite metadata and S3 blobs."""
        raw = self.db.get_trace_by_id(trace_id)
        if not raw:
            return None

        trace = raw["trace"]
        steps_raw = raw["steps"]
        effects_raw = raw["effects"]

        steps = []
        for s in steps_raw:
            fork_reasons = s.get("fork_reasons")
            if isinstance(fork_reasons, str):
                try:
                    fork_reasons = json.loads(fork_reasons)
                except json.JSONDecodeError:
                    fork_reasons = []

            step_entry: dict[str, Any] = {
                "step_id": s["step_id"],
                "kind": s["kind"],
                "t_virtual_ms": s["t_virtual_ms"],
                "parent_step": s.get("parent_step"),
                "request": {
                    "tool": s.get("tool_name"),
                    "args_ref": s.get("args_ref"),
                    "idempotency_key": s.get("idempotency_key"),
                    "declared_mutating": bool(s.get("mutating")),
                },
                "response": {
                    "status": "ok",
                    "body_ref": s.get("body_ref"),
                },
                "state_snapshot_ref": s.get("state_snapshot_ref"),
                "forkable": bool(s.get("forkable")),
                "fork_reasons": fork_reasons or [],
            }
            steps.append(step_entry)

        effects = []
        for e in effects_raw:
            delta = e.get("delta")
            if isinstance(delta, str):
                try:
                    delta = json.loads(delta)
                except json.JSONDecodeError:
                    pass

            effect_entry = {
                "effect_id": e["effect_id"],
                "step_id": e["step_id"],
                "type": e["type"],
                "resource": e["resource"],
                "delta": delta,
                "reversible": bool(e.get("reversible")),
                "idempotency_key": e.get("idem_key"),
                "observed_at_step": e["observed_at_step"],
            }
            effects.append(effect_entry)

        ctf_reconstructed: dict[str, Any] = {
            "trace_id": trace["trace_id"],
            "session_id": trace.get("session_id"),
            "agent": {
                "name": trace["agent_name"],
                "version": trace["agent_version"],
                "git_sha": trace.get("git_sha"),
            },
            "model": {
                "provider": trace["model_provider"],
                "model_id": trace["model_id"],
                "params": {
                    "temperature": trace.get("temperature", 0.0),
                    "seed": trace.get("seed"),
                },
            },
            "started_at": trace.get("captured_at"),
            "determinism_level": trace["determinism_lvl"],
            "steps": steps,
            "effects": effects,
            "final_state_ref": trace.get("final_state_ref"),
            "outcome": {
                "status": trace["outcome_status"],
                "outcome_status": trace["outcome_status"],
                "status_source": trace["status_source"],
                "cost_usd": trace.get("cost_usd"),
                "wall_ms": trace.get("wall_ms"),
            },
            "redaction_key_id": trace.get("redaction_key_id"),
        }

        return ctf_reconstructed
