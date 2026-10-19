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


EXACT_AGENT_NAMES = {
    "handle_customer_message",
    "handle_message",
    "process_customer_message",
    "process_message",
    "run_agent",
    "execute_agent",
    "call_agent",
    "chat_assistant",
    "solve_task",
}

EXACT_TOOL_NAMES = {
    "lookup_order_status",
    "lookup_order",
    "charge_payment",
    "issue_refund",
    "process_payment",
    "send_notification",
    "send_email",
    "database_lookup",
    "execute_db_query",
}

SKIP_DECORATORS = {
    "staticmethod",
    "classmethod",
    "property",
    "abstractmethod",
    "fixture",
    "pytest.fixture",
    "command",
    "callback",
    "get",
    "post",
    "put",
    "delete",
}

SKIP_FUNCTION_NAMES = {
    "main",
    "cli",
    "render",
    "format",
    "print",
    "setup",
    "init",
    "close",
    "clean",
    "cleanup",
    "parse",
    "validate",
    "tag",
    "badge",
    "export",
    "load",
    "dump",
    "read",
    "write",
    "get",
    "set",
    "update",
    "delete",
    "agent",
    "tool",
    "to_dict",
    "to_json",
    "from_dict",
    "from_json",
}


def is_ignored_file(file_path: Path | str) -> bool:
    """Returns True if the file belongs to test suites, framework internals, or build artifacts."""
    p = Path(file_path)
    parts = [part.lower() for part in p.parts]
    if any(
        part in (
            "tests",
            "test",
            "testing",
            "docs",
            "build",
            "dist",
            "node_modules",
            "sdk",
            ".venv",
            "venv",
            ".arc",
            ".git",
        )
        or part.startswith(".")
        for part in parts
    ):
        return True
    if p.name.startswith("test_") or p.name.endswith("_test.py") or p.name in ("conftest.py", "setup.py"):
        return True
    # If scanning inside ARC repository itself, avoid instrumenting framework internals
    if "arc" in parts and any(
        sub in parts for sub in ("cli", "control_plane", "execution", "ui")
    ):
        return True
    return False


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


def _has_skip_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Checks if node is decorated with non-agent/tool decorators like @staticmethod or @property."""
    for dec in node.decorator_list:
        dec_name = ""
        if isinstance(dec, ast.Name):
            dec_name = dec.id
        elif isinstance(dec, ast.Attribute):
            dec_name = dec.attr
        elif isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name):
                dec_name = dec.func.id
            elif isinstance(dec.func, ast.Attribute):
                dec_name = dec.func.attr
        if dec_name.lower() in SKIP_DECORATORS:
            return True
    return False


def _detect_candidate_type(
    node: ast.FunctionDef | ast.AsyncFunctionDef, filename: str
) -> str | None:
    """Classifies a function as trace_agent, trace_tool, or None with high precision."""
    if is_ignored_file(filename):
        return None

    # Skip private, dunder, and test functions
    if node.name.startswith(("_", "test_")):
        return None

    # Skip methods decorated with staticmethod, property, fixture, CLI, etc.
    if _has_skip_decorator(node):
        return None

    fn_lower = node.name.lower()
    if fn_lower in SKIP_FUNCTION_NAMES:
        return None

    # Check for explicit third-party tool decorators (e.g. @tool from LangChain/CrewAI)
    for dec in node.decorator_list:
        dec_name = ""
        if isinstance(dec, ast.Name):
            dec_name = dec.id
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            dec_name = dec.func.id
        if dec_name.lower() == "tool":
            return "trace_tool"

    # Agent Detection:
    if fn_lower in EXACT_AGENT_NAMES or (
        fn_lower.endswith("_agent") and not fn_lower.startswith(("is_", "get_", "set_", "has_"))
    ):
        return "trace_agent"

    # Tool Detection:
    TOOL_PREFIXES = (
        "lookup_",
        "fetch_",
        "charge_",
        "issue_",
        "process_payment",
        "send_notification",
        "send_email",
        "database_",
        "tool_",
    )
    if fn_lower in EXACT_TOOL_NAMES or any(
        fn_lower.startswith(prefix) for prefix in TOOL_PREFIXES
    ):
        return "trace_tool"

    # Deep AST call inspection: Look for LLM or external service invocation
    has_llm_call = False
    has_io_call = False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            call_repr = ""
            if isinstance(sub.func, ast.Attribute):
                prefix = getattr(sub.func.value, "id", "")
                call_repr = f"{prefix}.{sub.func.attr}".lower()
            elif isinstance(sub.func, ast.Name):
                call_repr = sub.func.id.lower()
            if any(
                term in call_repr
                for term in (
                    "chat.completions",
                    "messages.create",
                    "generate_content",
                    "create_react_agent",
                )
            ):
                has_llm_call = True
            if any(
                term in call_repr
                for term in (
                    "requests.post",
                    "requests.get",
                    "httpx.post",
                    "httpx.get",
                    "stripe.",
                    "boto3.",
                )
            ):
                has_io_call = True

    if has_llm_call:
        return "trace_agent"
    if has_io_call and not fn_lower.startswith(("test_", "assert_", "check_")):
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
