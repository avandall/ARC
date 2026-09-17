"""Schema Invariant Miner for OpenAPI Specs & Database Schemas (TASK-P3-002).

Extracts invariant candidates from OpenAPI schemas (YAML/JSON) and SQL DDL schemas,
tagging appropriate sources (db_constraint, openapi_schema) and categories (authority, safety, conservation).
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from arc.control_plane.miner.ast_miner import ASTMiner, MinedCandidate, compute_candidate_id

logger = logging.getLogger(__name__)


class SchemaMiner:
    """Miner for schema-based constraints (OpenAPI & SQL DDL)."""

    def __init__(self) -> None:
        self.ast_miner = ASTMiner()
        self.mined_candidates: dict[str, MinedCandidate] = {}

    def clear(self) -> None:
        """Clears accumulated candidates."""
        self.ast_miner.clear()
        self.mined_candidates.clear()

    def get_candidates(self) -> list[MinedCandidate]:
        """Returns all deduplicated mined candidates."""
        all_candidates = dict(self.mined_candidates)
        for cand in self.ast_miner.get_candidates():
            if cand.id not in all_candidates:
                all_candidates[cand.id] = cand
        return list(all_candidates.values())

    def _add_candidate(self, candidate: MinedCandidate) -> None:
        """Adds a candidate enforcing deduplication."""
        if candidate.id not in self.mined_candidates:
            self.mined_candidates[candidate.id] = candidate

    def mine_sql_ddl(self, ddl_str: str, filename: str = "") -> list[MinedCandidate]:
        """Delegates SQL DDL constraint mining to tree-sitter ASTMiner."""
        return self.ast_miner.mine_sql_ddl(ddl_str, filename=filename)

    def mine_openapi_spec(
        self, spec_input: str | dict[str, Any], filename: str = ""
    ) -> list[MinedCandidate]:
        """Parses an OpenAPI specification (YAML string, JSON string, or dict) and extracts authority invariants."""
        candidates: list[MinedCandidate] = []

        spec: dict[str, Any] = {}
        if isinstance(spec_input, dict):
            spec = spec_input
        elif isinstance(spec_input, str):
            try:
                # Try YAML safe load (which also handles JSON)
                loaded = yaml.safe_load(spec_input)
                if isinstance(loaded, dict):
                    spec = loaded
                else:
                    logger.warning(f"Parsed OpenAPI spec '{filename}' is not a dict structure.")
                    return []
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Syntax error parsing OpenAPI spec '{filename}': {e}. Skipping safely.")
                return []

        paths = spec.get("paths", {})
        if not isinstance(paths, dict):
            return candidates

        for path_url, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            for method, operation in path_item.items():
                if not isinstance(operation, dict):
                    continue

                scopes: set[str] = set()

                # 1. Extract from operation-level 'scopes' field
                if "scopes" in operation and isinstance(operation["scopes"], list):
                    for s in operation["scopes"]:
                        if isinstance(s, str):
                            scopes.add(s)

                # 2. Extract from operation-level 'x-scopes' field
                if "x-scopes" in operation and isinstance(operation["x-scopes"], list):
                    for s in operation["x-scopes"]:
                        if isinstance(s, str):
                            scopes.add(s)

                # 3. Extract from operation-level 'security' field
                security = operation.get("security", [])
                if isinstance(security, list):
                    for sec_req in security:
                        if isinstance(sec_req, dict):
                            for scope_list in sec_req.values():
                                if isinstance(scope_list, list):
                                    for s in scope_list:
                                        if isinstance(s, str):
                                            scopes.add(s)

                # Create authority invariant candidate for each required scope
                for scope in sorted(scopes):
                    category = "authority"
                    check_expr = f"'{scope}' in context.scopes"
                    statement = (
                        f"Endpoint {method.upper()} {path_url} requires scope '{scope}'"
                    )
                    cand_id = compute_candidate_id(statement, category, check_expr)
                    cand = MinedCandidate(
                        id=cand_id,
                        statement=statement,
                        category=category,
                        check=check_expr,
                        severity="critical",
                        source=["openapi_schema"],
                        metadata={
                            "endpoint": path_url,
                            "method": method.upper(),
                            "scope": scope,
                            "filename": filename,
                        },
                    )
                    candidates.append(cand)
                    self._add_candidate(cand)

        return candidates


def mine_invariants_from_openapi_spec(spec_input: str | dict[str, Any]) -> list[MinedCandidate]:
    """Helper function to mine invariants from OpenAPI spec content."""
    miner = SchemaMiner()
    return miner.mine_openapi_spec(spec_input)
