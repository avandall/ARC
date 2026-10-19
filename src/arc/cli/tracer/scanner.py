"""Auto Tracing AST Scanner for Agent & Tool functions (TASK-CLI-004).

Scans Python source code using AST analysis to identify candidate functions
for `@trace_agent` and `@trace_tool` decorators.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TraceCandidate:
    """Represents a proposed decorator attachment to a function."""

    file_path: Path
    function_name: str
    decorator_type: str  # "trace_agent" or "trace_tool"
    line_number: int  # 1-indexed
    original_code: str
    modified_code: str
    diff_snippet: str


AGENT_NAME_KEYWORDS = {
    "handle_message",
    "handle_customer_message",
    "process_message",
    "process_customer_message",
    "run_agent",
    "call_agent",
    "chat_assistant",
    "agent",
    "assistant",
    "handle_ticket",
    "execute_agent",
    "solve_task",
}

AGENT_ARG_KEYWORDS = {
    "message",
    "msg",
    "query",
    "user_query",
    "prompt",
    "user_input",
}

TOOL_NAME_KEYWORDS = {
    "lookup",
    "lookup_order",
    "lookup_order_status",
    "fetch",
    "query",
    "execute_tool",
    "call_api",
    "charge_payment",
    "issue_refund",
    "send_email",
    "send_notification",
    "payment_gateway",
    "db_query",
    "database_lookup",
}


def _has_tracing_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Checks whether the function already has @trace_agent or @trace_tool."""
    for dec in node.decorator_list:
        dec_name = ""
        if isinstance(dec, ast.Name):
            dec_name = dec.id
        elif isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name):
                dec_name = dec.func.id
            elif isinstance(dec.func, ast.Attribute):
                dec_name = dec.func.attr
        if dec_name in ("trace_agent", "trace_tool"):
            return True
    return False


def _detect_candidate_type(
    node: ast.FunctionDef | ast.AsyncFunctionDef, filename: str
) -> str | None:
    """Classifies a function as trace_agent, trace_tool, or None."""
    fn_lower = node.name.lower()
    args_lower = {arg.arg.lower() for arg in node.args.args}

    # Agent check
    if any(k in fn_lower for k in AGENT_NAME_KEYWORDS):
        return "trace_agent"
    if any(a in args_lower for a in AGENT_ARG_KEYWORDS):
        return "trace_agent"

    # Tool check
    if any(k in fn_lower for k in TOOL_NAME_KEYWORDS):
        return "trace_tool"
    if "tool" in fn_lower or "api" in fn_lower or "db" in fn_lower:
        return "trace_tool"
    if any(
        pattern in filename.lower() for pattern in ("tool", "service", "api", "gateway")
    ) and not fn_lower.startswith("_"):
        return "trace_tool"

    return None


def scan_code_for_tracing(code_text: str, filename: str = "<string>") -> list[TraceCandidate]:
    """Scans Python code and generates decorator attachment candidates."""
    try:
        tree = ast.parse(code_text, filename=filename)
    except SyntaxError:
        return []

    lines = code_text.splitlines(keepends=True)
    candidates: list[TraceCandidate] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        if _has_tracing_decorator(node):
            continue

        cand_type = _detect_candidate_type(node, filename)
        if not cand_type:
            continue

        line_idx = node.lineno - 1
        def_line = lines[line_idx]
        indent = def_line[: len(def_line) - len(def_line.lstrip())]

        decorator_str = f"{indent}@{cand_type}(name=\"{node.name}\")\n"

        # Check if import is needed
        import_stmt = f"from arc import {cand_type}\n"
        needs_import = f"from arc import {cand_type}" not in code_text and "from arc import *" not in code_text

        new_lines = list(lines)
        new_lines.insert(line_idx, decorator_str)
        if needs_import:
            # Insert import after docstring or future imports if present, else at line 0
            insert_pos = 0
            if (
                len(new_lines) > 0
                and isinstance(tree.body[0] if tree.body else None, ast.Expr)
                and isinstance(getattr(tree.body[0], "value", None), ast.Constant)
            ):
                insert_pos = getattr(tree.body[0], "end_lineno", 1)
            new_lines.insert(insert_pos, import_stmt)

        modified_code = "".join(new_lines)

        # Syntax check
        try:
            ast.parse(modified_code)
        except SyntaxError:
            continue

        diff_snippet = (
            f"- {def_line.strip()}\n"
            f"+ {decorator_str.strip()}\n"
            f"+ {def_line.strip()}"
        )

        candidates.append(
            TraceCandidate(
                file_path=Path(filename),
                function_name=node.name,
                decorator_type=cand_type,
                line_number=node.lineno,
                original_code=code_text,
                modified_code=modified_code,
                diff_snippet=diff_snippet,
            )
        )

    return candidates


def scan_file_for_tracing(file_path: Path) -> list[TraceCandidate]:
    """Scans a single Python file for tracing candidates."""
    target_path = Path(file_path).resolve()
    if not target_path.is_file():
        return []

    try:
        content = target_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    cands = scan_code_for_tracing(content, filename=str(target_path))
    for c in cands:
        c.file_path = target_path
    return cands


def apply_candidate(candidate: TraceCandidate) -> None:
    """Applies candidate modifications to the target file safely without overwriting earlier changes."""
    path = Path(candidate.file_path)
    if not path.is_file():
        path.write_text(candidate.modified_code, encoding="utf-8")
        return

    current_code = path.read_text(encoding="utf-8")

    # If the file hasn't been changed from original_code, candidate.modified_code is completely valid
    if current_code == candidate.original_code:
        path.write_text(candidate.modified_code, encoding="utf-8")
        return

    # If current_code already contains the decorator for this function, no-op
    try:
        tree = ast.parse(current_code)
    except SyntaxError:
        path.write_text(candidate.modified_code, encoding="utf-8")
        return

    target_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == candidate.function_name
        ):
            target_node = node
            break

    if target_node is None or _has_tracing_decorator(target_node):
        return

    lines = current_code.splitlines(keepends=True)
    def_line_idx = target_node.lineno - 1
    def_line = lines[def_line_idx]
    indent = def_line[: len(def_line) - len(def_line.lstrip())]
    decorator_str = f"{indent}@{candidate.decorator_type}(name=\"{candidate.function_name}\")\n"

    lines.insert(def_line_idx, decorator_str)

    cand_import = f"from arc import {candidate.decorator_type}\n"
    if (
        f"from arc import {candidate.decorator_type}" not in current_code
        and "from arc import *" not in current_code
    ):
        insert_pos = 0
        if (
            len(lines) > 0
            and isinstance(tree.body[0] if tree.body else None, ast.Expr)
            and isinstance(getattr(tree.body[0], "value", None), ast.Constant)
        ):
            insert_pos = getattr(tree.body[0], "end_lineno", 1)
        lines.insert(insert_pos, cand_import)

    updated_code = "".join(lines)
    try:
        ast.parse(updated_code)
        path.write_text(updated_code, encoding="utf-8")
    except SyntaxError:
        pass
