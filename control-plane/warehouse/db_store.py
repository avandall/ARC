"""Database Store for Trace Warehouse (PostgreSQL / SQLite compatibility).

Handles CRUD operations for traces, steps, and effects with RLS enforcement.
"""

import json
import sqlite3
from typing import Any


class DatabaseStore:
    """Database adapter supporting SQL persistence and RLS isolation."""

    def __init__(self, db_url: str | None = None) -> None:
        self.db_url = db_url or ":memory:"
        self._allowed_agents: list[str] | None = None
        self._conn = sqlite3.connect(self.db_url, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_sqlite_schema()

    def _init_sqlite_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                session_id TEXT,
                agent_name TEXT NOT NULL,
                agent_version TEXT NOT NULL,
                git_sha TEXT,
                model_provider TEXT NOT NULL,
                model_id TEXT NOT NULL,
                temperature REAL DEFAULT 0.0,
                seed INTEGER,
                determinism_lvl TEXT NOT NULL,
                outcome_status TEXT NOT NULL,
                status_source TEXT NOT NULL,
                cost_usd REAL,
                wall_ms INTEGER,
                captured_at TEXT NOT NULL DEFAULT (datetime('now')),
                redaction_key_id TEXT NOT NULL,
                final_state_ref TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS steps (
                trace_id TEXT NOT NULL,
                step_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                t_virtual_ms INTEGER NOT NULL,
                parent_step INTEGER,
                tool_name TEXT,
                args_ref TEXT,
                body_ref TEXT,
                idempotency_key TEXT,
                mutating INTEGER NOT NULL DEFAULT 0,
                forkable INTEGER NOT NULL DEFAULT 0,
                fork_reasons TEXT,
                state_snapshot_ref TEXT,
                PRIMARY KEY (trace_id, step_id),
                FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS effects (
                effect_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                step_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                resource TEXT NOT NULL,
                delta TEXT,
                reversible INTEGER NOT NULL,
                idem_key TEXT,
                observed_at_step INTEGER NOT NULL,
                FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
            )
            """
        )
        self._conn.commit()

    def set_allowed_agents(self, allowed_agents: str | None) -> None:
        """Sets the RLS setting `arc.allowed_agents` for the session context."""
        if allowed_agents is None:
            self._allowed_agents = None
        else:
            self._allowed_agents = [a.strip() for a in allowed_agents.split(",") if a.strip()]

    def insert_trace(
        self,
        trace_meta: dict[str, Any],
        steps_meta: list[dict[str, Any]],
        effects_meta: list[dict[str, Any]],
    ) -> None:
        """Inserts trace metadata, step metadata, and effect metadata into database."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO traces (
                trace_id, session_id, agent_name, agent_version, git_sha,
                model_provider, model_id, temperature, seed, determinism_lvl,
                outcome_status, status_source, cost_usd, wall_ms, captured_at,
                redaction_key_id, final_state_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
            """,
            (
                trace_meta.get("trace_id"),
                trace_meta.get("session_id"),
                trace_meta.get("agent_name"),
                trace_meta.get("agent_version"),
                trace_meta.get("git_sha"),
                trace_meta.get("model_provider"),
                trace_meta.get("model_id"),
                trace_meta.get("temperature", 0.0),
                trace_meta.get("seed"),
                trace_meta.get("determinism_lvl", "L2"),
                trace_meta.get("outcome_status", "unknown"),
                trace_meta.get("status_source", "agent_self_report"),
                trace_meta.get("cost_usd"),
                trace_meta.get("wall_ms"),
                trace_meta.get("redaction_key_id", "default"),
                trace_meta.get("final_state_ref"),
            ),
        )

        for s in steps_meta:
            fork_reasons = s.get("fork_reasons")
            fork_reasons_str = json.dumps(fork_reasons) if isinstance(fork_reasons, list) else None
            cursor.execute(
                """
                INSERT OR REPLACE INTO steps (
                    trace_id, step_id, kind, t_virtual_ms, parent_step,
                    tool_name, args_ref, body_ref, idempotency_key, mutating,
                    forkable, fork_reasons, state_snapshot_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_meta.get("trace_id"),
                    s.get("step_id"),
                    s.get("kind"),
                    s.get("t_virtual_ms", 0),
                    s.get("parent_step"),
                    s.get("tool_name"),
                    s.get("args_ref"),
                    s.get("body_ref"),
                    s.get("idempotency_key"),
                    1 if s.get("mutating") else 0,
                    1 if s.get("forkable") else 0,
                    fork_reasons_str,
                    s.get("state_snapshot_ref"),
                ),
            )

        for e in effects_meta:
            delta = e.get("delta")
            delta_str = json.dumps(delta) if isinstance(delta, (dict, list)) else None
            cursor.execute(
                """
                INSERT OR REPLACE INTO effects (
                    effect_id, trace_id, step_id, type, resource, delta,
                    reversible, idem_key, observed_at_step
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e.get("effect_id"),
                    trace_meta.get("trace_id"),
                    e.get("step_id"),
                    e.get("type"),
                    e.get("resource"),
                    delta_str,
                    1 if e.get("reversible") else 0,
                    e.get("idem_key") or e.get("idempotency_key"),
                    e.get("observed_at_step", e.get("step_id", 0)),
                ),
            )

        self._conn.commit()

    def get_traces(
        self,
        agent: str | None = None,
        outcome_status: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Queries traces table respecting RLS allowed_agents settings and filters."""
        query = "SELECT * FROM traces WHERE 1=1"
        params: list[Any] = []

        # Enforce RLS
        if self._allowed_agents is not None:
            placeholders = ",".join(["?"] * len(self._allowed_agents))
            query += f" AND agent_name IN ({placeholders})"
            params.extend(self._allowed_agents)

        if agent:
            query += " AND agent_name = ?"
            params.append(agent)

        if outcome_status:
            query += " AND outcome_status = ?"
            params.append(outcome_status)

        if since:
            query += " AND captured_at >= ?"
            params.append(since)

        cursor = self._conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_trace_by_id(self, trace_id: str) -> dict[str, Any] | None:
        """Retrieves trace metadata along with associated steps and effects."""
        query = "SELECT * FROM traces WHERE trace_id = ?"
        params: list[Any] = [trace_id]

        if self._allowed_agents is not None:
            placeholders = ",".join(["?"] * len(self._allowed_agents))
            query += f" AND agent_name IN ({placeholders})"
            params.extend(self._allowed_agents)

        cursor = self._conn.cursor()
        cursor.execute(query, params)
        trace_row = cursor.fetchone()
        if not trace_row:
            return None

        trace_meta = dict(trace_row)

        cursor.execute("SELECT * FROM steps WHERE trace_id = ? ORDER BY step_id ASC", (trace_id,))
        step_rows = cursor.fetchall()
        steps = [dict(s) for s in step_rows]

        cursor.execute("SELECT * FROM effects WHERE trace_id = ?", (trace_id,))
        effect_rows = cursor.fetchall()
        effects = [dict(e) for e in effect_rows]

        return {"trace": trace_meta, "steps": steps, "effects": effects}
