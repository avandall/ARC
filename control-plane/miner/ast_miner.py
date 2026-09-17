"""AST & Schema Invariant Miner using tree-sitter (TASK-P3-002).

Extracts invariant candidates from source code (Python, SQL DDL) using tree-sitter AST parsing,
enforcing deduplication based on normalized candidate hashes and safe error handling.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import tree_sitter

logger = logging.getLogger(__name__)

# Load tree-sitter language parsers safely
PY_LANGUAGE: tree_sitter.Language | None = None
SQL_LANGUAGE: tree_sitter.Language | None = None

try:
    import tree_sitter_python as tspython
    PY_LANGUAGE = tree_sitter.Language(tspython.language())
except Exception as e:  # noqa: BLE001
    logger.warning(f"Failed to load tree-sitter Python language: {e}")

try:
    import tree_sitter_sql as tssql
    SQL_LANGUAGE = tree_sitter.Language(tssql.language())
except Exception as e:  # noqa: BLE001
    logger.warning(f"Failed to load tree-sitter SQL language: {e}")


@dataclass
class MinedCandidate:
    """Represents an invariant candidate mined from source code or schema AST."""

    id: str
    statement: str
    category: str  # safety | conservation | authority | idempotence | ordering | budget | consistency
    check: str
    severity: str = "critical"
    source: list[str] = field(default_factory=list)
    status: str = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "category": self.category,
            "check": self.check,
            "severity": self.severity,
            "source": self.source,
            "status": self.status,
            "metadata": self.metadata,
        }


def normalize_expression(expr: str) -> str:
    """Normalizes expression string for deterministic deduplication."""
    s = expr.strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def compute_candidate_id(statement: str, category: str, check: str) -> str:
    """Computes a deterministic candidate ID based on normalized category and check expression."""
    key = f"{category.strip().lower()}:{normalize_expression(check or statement)}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"INV-MINED-{digest.upper()}"


class ASTMiner:
    """Miner using tree-sitter AST parsing to extract invariant candidates."""

    def __init__(self) -> None:
        self.mined_candidates: dict[str, MinedCandidate] = {}

    def clear(self) -> None:
        """Clears stored candidates."""
        self.mined_candidates.clear()

    def get_candidates(self) -> list[MinedCandidate]:
        """Returns deduplicated mined candidates."""
        return list(self.mined_candidates.values())

    def _add_candidate(self, candidate: MinedCandidate) -> None:
        """Adds candidate with deduplication by ID."""
        if candidate.id not in self.mined_candidates:
            self.mined_candidates[candidate.id] = candidate

    def mine_python_source(self, code_str: str, filename: str = "") -> list[MinedCandidate]:
        """Parses Python source code and extracts assert/condition invariants safely."""
        if not PY_LANGUAGE:
            logger.warning("Python tree-sitter language not available")
            return []

        candidates: list[MinedCandidate] = []
        try:
            parser = tree_sitter.Parser(PY_LANGUAGE)
            tree = parser.parse(code_str.encode("utf-8"))

            if tree.root_node.has_error:
                logger.warning(f"Syntax error in Python file '{filename}'. Processing valid nodes safely.")

            def _traverse(node: tree_sitter.Node) -> None:
                if node.type == "ERROR" or node.is_error:
                    return

                if node.type == "assert_statement":
                    stmt_text = code_str[node.start_byte:node.end_byte].strip()
                    children = [c for c in node.children if c.type not in ("assert", ",")]
                    if children:
                        expr_node = children[0]
                        check_expr = code_str[expr_node.start_byte:expr_node.end_byte].strip()
                        category = (
                            "conservation"
                            if any(k in check_expr.lower() for k in ["refund", "amount", "total", "balance", "price", "cost"])
                            else "safety"
                        )
                        cand_id = compute_candidate_id(stmt_text, category, check_expr)
                        cand = MinedCandidate(
                            id=cand_id,
                            statement=f"Assert check: {check_expr}",
                            category=category,
                            check=check_expr,
                            source=["python_ast"],
                            metadata={"filename": filename},
                        )
                        candidates.append(cand)
                        self._add_candidate(cand)

                for child in node.children:
                    _traverse(child)

            _traverse(tree.root_node)

        except Exception as e:  # noqa: BLE001
            logger.error(f"Error parsing Python source '{filename}': {e}")

        return candidates

    def mine_sql_ddl(self, ddl_str: str, filename: str = "") -> list[MinedCandidate]:
        """Parses SQL DDL statements and extracts CHECK, FOREIGN KEY, and NOT NULL constraints."""
        candidates: list[MinedCandidate] = []

        if not SQL_LANGUAGE:
            logger.warning("SQL tree-sitter language not available")
            return candidates

        try:
            parser = tree_sitter.Parser(SQL_LANGUAGE)
            tree = parser.parse(ddl_str.encode("utf-8"))

            if tree.root_node.has_error:
                logger.warning(f"Syntax error in SQL source '{filename}'. Processing valid nodes safely.")

            def _get_table_name(create_table_node: tree_sitter.Node) -> str:
                for child in create_table_node.children:
                    if child.type in ("object_reference", "identifier"):
                        return ddl_str[child.start_byte:child.end_byte].strip().strip('"').strip('`').strip("'")
                return "table"

            def _traverse_sql(node: tree_sitter.Node, current_table: str = "table") -> None:
                if node.type == "ERROR" or node.is_error:
                    return

                table_name = current_table
                if node.type == "create_table":
                    table_name = _get_table_name(node)

                if node.type == "constraint":
                    constraint_text = ddl_str[node.start_byte:node.end_byte].strip()
                    upper_text = constraint_text.upper()
                    if "CHECK" in upper_text:
                        match = re.search(r"CHECK\s*\((.*)\)", constraint_text, re.IGNORECASE | re.DOTALL)
                        if match:
                            check_expr = match.group(1).strip()
                            category = (
                                "conservation"
                                if any(k in check_expr.lower() for k in ["refund", "amount", "total", "balance", "sum", "price", "cost"])
                                else "safety"
                            )
                            statement = f"Table {table_name} CHECK ({check_expr})"
                            cand_id = compute_candidate_id(statement, category, check_expr)
                            cand = MinedCandidate(
                                id=cand_id,
                                statement=statement,
                                category=category,
                                check=check_expr,
                                source=["db_constraint"],
                                metadata={"table": table_name, "filename": filename},
                            )
                            candidates.append(cand)
                            self._add_candidate(cand)
                    elif "FOREIGN KEY" in upper_text or "REFERENCES" in upper_text:
                        category = "consistency"
                        statement = f"Table {table_name} FOREIGN KEY {constraint_text}"
                        cand_id = compute_candidate_id(statement, category, constraint_text)
                        cand = MinedCandidate(
                            id=cand_id,
                            statement=statement,
                            category=category,
                            check=constraint_text,
                            source=["db_constraint"],
                            metadata={"table": table_name, "filename": filename},
                        )
                        candidates.append(cand)
                        self._add_candidate(cand)

                elif node.type == "column_definition":
                    col_text = ddl_str[node.start_byte:node.end_byte].strip()
                    if "NOT NULL" in col_text.upper():
                        col_parts = col_text.split()
                        col_name = col_parts[0] if col_parts else "column"
                        category = "safety"
                        check_expr = f"{table_name}.{col_name} IS NOT NULL"
                        statement = f"Table {table_name} column {col_name} NOT NULL"
                        cand_id = compute_candidate_id(statement, category, check_expr)
                        cand = MinedCandidate(
                            id=cand_id,
                            statement=statement,
                            category=category,
                            check=check_expr,
                            source=["db_constraint"],
                            metadata={"table": table_name, "column": col_name, "filename": filename},
                        )
                        candidates.append(cand)
                        self._add_candidate(cand)

                for child in node.children:
                    _traverse_sql(child, table_name)

            _traverse_sql(tree.root_node)

        except Exception as e:  # noqa: BLE001
            logger.error(f"Error parsing SQL DDL '{filename}': {e}")

        return candidates


def mine_invariants_from_sql_ddl_constraints(sql_ddl: str) -> list[MinedCandidate]:
    """Helper function to mine invariants from SQL DDL content using tree-sitter AST."""
    miner = ASTMiner()
    return miner.mine_sql_ddl(sql_ddl)
