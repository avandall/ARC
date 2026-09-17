"""Unit tests for AST & Schema Invariant Miner (TASK-P3-002)."""

from __future__ import annotations

import os
import sys

# Ensure control-plane is in sys.path
sys.path.insert(0, os.path.abspath("control-plane"))

from miner import (
    ASTMiner,
    SchemaMiner,
    mine_invariants_from_openapi_spec,
    mine_invariants_from_sql_ddl_constraints,
)


def test_mine_invariants_from_sql_ddl_constraints() -> None:
    """Happy Path 1: Mine invariants from SQL DDL CHECK constraints using tree-sitter."""
    ddl = """
    CREATE TABLE orders (
        id INT PRIMARY KEY,
        user_id INT NOT NULL,
        total_amount NUMERIC NOT NULL,
        refund_amount NUMERIC,
        CONSTRAINT check_refund CHECK (refund_amount <= total_amount),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """
    candidates = mine_invariants_from_sql_ddl_constraints(ddl)

    assert len(candidates) >= 1

    # Check conservation candidate mined from CHECK constraint
    conservation_cands = [c for c in candidates if c.category == "conservation"]
    assert len(conservation_cands) >= 1

    cand = conservation_cands[0]
    assert "db_constraint" in cand.source
    assert "refund_amount" in cand.check
    assert "total_amount" in cand.check
    assert cand.severity == "critical"


def test_mine_invariants_from_openapi_spec() -> None:
    """Happy Path 2: Mine authority invariants from OpenAPI schema scopes."""
    openapi_yaml = """
    openapi: 3.0.0
    info:
      title: Payment Service API
      version: 1.0.0
    paths:
      /refunds:
        post:
          summary: Process refund
          scopes:
            - "payments:write"
          security:
            - oauth2:
                - "payments:write"
    """
    candidates = mine_invariants_from_openapi_spec(openapi_yaml)

    assert len(candidates) >= 1

    authority_cands = [c for c in candidates if c.category == "authority"]
    assert len(authority_cands) >= 1

    cand = authority_cands[0]
    assert "openapi_schema" in cand.source
    assert "payments:write" in cand.check or cand.metadata.get("scope") == "payments:write"
    assert cand.metadata.get("endpoint") == "/refunds"


def test_ast_miner_handles_syntax_errors_in_source() -> None:
    """Edge Case 1: Handles incomplete / malformed Python/SQL/OpenAPI gracefully without crashing."""
    broken_py = "def broken_func(a, b:\n    assert a <"
    broken_sql = "CREATE TABLE orders (id INT, CHECK refund_amount <="
    broken_yaml = "openapi: 3.0.0\npaths: /refunds: {invalid yaml: [["

    ast_miner = ASTMiner()
    py_cands = ast_miner.mine_python_source(broken_py, filename="broken.py")
    assert isinstance(py_cands, list)  # Should not raise exception

    sql_cands = ast_miner.mine_sql_ddl(broken_sql, filename="broken.sql")
    assert isinstance(sql_cands, list)  # Should not raise exception

    schema_miner = SchemaMiner()
    yaml_cands = schema_miner.mine_openapi_spec(broken_yaml, filename="broken.yaml")
    assert isinstance(yaml_cands, list)  # Should not raise exception


def test_miner_deduplicates_identical_mined_candidates() -> None:
    """Edge Case 2: Deduplicates identical mined candidates based on normalized hash."""
    ddl1 = "CREATE TABLE orders (total_amount NUMERIC, refund_amount NUMERIC, CHECK (refund_amount <= total_amount));"
    ddl2 = "CREATE TABLE orders_v2 (total_amount NUMERIC, refund_amount NUMERIC, CHECK ( refund_amount <= total_amount ));"

    miner = ASTMiner()
    miner.mine_sql_ddl(ddl1, filename="migration_001.sql")
    miner.mine_sql_ddl(ddl2, filename="migration_002.sql")

    all_candidates = miner.get_candidates()
    conservation_cands = [c for c in all_candidates if c.category == "conservation"]

    # Deduplicated by normalized check expression: 'refund_amount <= total_amount'
    assert len(conservation_cands) == 1
