-- Migration 001: Initial Schema for ARC+ Trace Warehouse & Invariants
-- Based on ARC+ Spec v4.0 §4.7, §8.3, §12 and TECH_CONTEXT.md

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Traces Table (CTF Metadata)
CREATE TABLE IF NOT EXISTS traces (
  trace_id          TEXT PRIMARY KEY,
  session_id        TEXT,
  agent_name        TEXT NOT NULL,
  agent_version     TEXT NOT NULL,
  git_sha           TEXT,
  model_provider    TEXT NOT NULL,
  model_id          TEXT NOT NULL,
  temperature       NUMERIC(3,2) DEFAULT 0.0,
  seed              BIGINT,
  determinism_lvl   TEXT NOT NULL CHECK (determinism_lvl IN ('L0','L1','L2','L3')),
  outcome_status    TEXT NOT NULL CHECK (outcome_status IN (
                      'completed', 'agent_error', 'escalated_to_human', 
                      'timeout', 'aborted', 'unknown'
                    )),
  status_source     TEXT NOT NULL CHECK (status_source IN (
                      'human_triage', 'reconciliation_webhook', 
                      'agent_self_report', 'inferred_no_terminal_event'
                    )),
  cost_usd          NUMERIC(10,4),
  wall_ms           BIGINT,
  captured_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  redaction_key_id  TEXT NOT NULL,
  final_state_ref   TEXT
);

-- Row-Level Security (RLS) internal access policy by agent_name
ALTER TABLE traces ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_isolation_policy ON traces;
CREATE POLICY agent_isolation_policy ON traces
  FOR ALL
  USING (
    current_setting('arc.allowed_agents', true) IS NULL 
    OR agent_name = ANY(string_to_array(current_setting('arc.allowed_agents', true), ','))
  );

-- 2. Steps Table (Atomic Units & Potential Fork Points)
CREATE TABLE IF NOT EXISTS steps (
  trace_id          TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
  step_id           INT NOT NULL,
  kind              TEXT NOT NULL CHECK (kind IN (
                      'model_decision', 'tool_call', 'human_gate', 
                      'external_event', 'retry'
                    )),
  t_virtual_ms      BIGINT NOT NULL,
  parent_step       INT,
  tool_name         TEXT,
  args_ref          TEXT,
  body_ref          TEXT,
  idempotency_key   TEXT,
  mutating          BOOLEAN NOT NULL DEFAULT FALSE,
  forkable          BOOLEAN NOT NULL DEFAULT FALSE,
  fork_reasons      TEXT[],
  state_snapshot_ref TEXT,
  PRIMARY KEY (trace_id, step_id)
);

-- 3. Effects Table (Side-Effect Ledger)
CREATE TABLE IF NOT EXISTS effects (
  effect_id         TEXT PRIMARY KEY,
  trace_id          TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
  step_id           INT NOT NULL,
  type              TEXT NOT NULL,
  resource          TEXT NOT NULL,
  delta             JSONB,
  reversible        BOOLEAN NOT NULL,
  idem_key          TEXT,
  observed_at_step  INT NOT NULL
);

-- 4. Fork Runs Table (Manages Parallel K-Runs)
CREATE TABLE IF NOT EXISTS fork_runs (
  run_id            TEXT PRIMARY KEY,
  base_trace        TEXT NOT NULL REFERENCES traces(trace_id),
  fault_spec        JSONB NOT NULL,
  k                 INT NOT NULL,
  violations        JSONB,
  cassette_miss_rate NUMERIC(4,3) NOT NULL,
  cost_usd          NUMERIC(10,4),
  status            TEXT NOT NULL CHECK (status IN (
                      'running', 'completed', 'budget_exceeded', 'aborted', 'infra_error'
                    )),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. Invariant Candidates Table (Invariant Candidates Proposed by Miner)
CREATE TABLE IF NOT EXISTS invariant_candidates (
  candidate_id      TEXT PRIMARY KEY,
  statement         TEXT NOT NULL,
  category          TEXT NOT NULL CHECK (category IN (
                      'safety', 'conservation', 'idempotence', 
                      'ordering', 'authority', 'budget', 'consistency'
                    )),
  support           INT NOT NULL DEFAULT 0,
  counter_examples  INT NOT NULL DEFAULT 0,
  sources           TEXT[] NOT NULL,
  citation_unverified BOOLEAN NOT NULL DEFAULT FALSE,
  status            TEXT NOT NULL CHECK (status IN (
                      'pending', 'approved', 'rejected', 'quarantined'
                    )),
  proposed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Rejected Candidates Table (Deduplication of Rejected Candidates - §8.3)
CREATE TABLE IF NOT EXISTS rejected_candidates (
  statement_hash    TEXT PRIMARY KEY,
  original_candidate_id TEXT,
  reason            TEXT NOT NULL,
  rejected_by       TEXT NOT NULL,
  rejected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 7. Escaped Bugs History Table (§11.2)
CREATE TABLE IF NOT EXISTS escaped_bugs (
  incident_id       TEXT PRIMARY KEY,
  trace_id          TEXT NOT NULL REFERENCES traces(trace_id),
  linked_invariant  TEXT,
  root_cause        TEXT NOT NULL,
  tagged_by         TEXT NOT NULL,
  tagged_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_traces_agent_name ON traces(agent_name);
CREATE INDEX IF NOT EXISTS idx_traces_outcome_status ON traces(outcome_status);
CREATE INDEX IF NOT EXISTS idx_steps_trace_id ON steps(trace_id);
CREATE INDEX IF NOT EXISTS idx_effects_trace_id ON effects(trace_id);
