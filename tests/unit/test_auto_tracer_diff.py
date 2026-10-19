"""Unit tests for Auto Tracing AST Scanner & Interactive Diff Reviewer (TASK-CLI-004).

Covers:
- AST scanner detecting agent and tool functions
- Skipping functions with existing @trace_agent or @trace_tool
- Non-destructive code mutation with valid syntax and import injection
- Interactive Diff Box rendering with green/red lines
- User action handling: [y] accept, [n] reject, [a] accept all, [q] cancel
"""

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from arc.cli.tracer.scanner import (
    scan_code_for_tracing,
    scan_file_for_tracing,
)
from arc.cli.ui.diff import render_diff_box, review_and_apply_candidates


def _to_plain_text(rich_renderable: Any) -> str:
    """Renders a Rich markup string or renderable object to plain text."""
    console = Console(record=True, width=120, force_terminal=False)
    console.print(rich_renderable)
    return console.export_text()


def test_scanner_identifies_agent_functions() -> None:
    """Verifies that message/agent handlers are identified for @trace_agent."""
    code = """def handle_customer_message(user_id: str, message: str):\n    return f"Processed {message}"\n"""
    candidates = scan_code_for_tracing(code, filename="agent.py")

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.function_name == "handle_customer_message"
    assert cand.decorator_type == "trace_agent"
    assert "@trace_agent" in cand.modified_code
    assert "from arc import trace_agent" in cand.modified_code

    # Syntax integrity check
    parsed = ast.parse(cand.modified_code)
    assert parsed is not None


def test_scanner_identifies_tool_functions() -> None:
    """Verifies that DB/API tools are identified for @trace_tool."""
    code = """def lookup_order_status(order_id: str) -> dict:\n    return {"order_id": order_id, "status": "shipped"}\n"""
    candidates = scan_code_for_tracing(code, filename="tools.py")

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.function_name == "lookup_order_status"
    assert cand.decorator_type == "trace_tool"
    assert "@trace_tool" in cand.modified_code
    assert "from arc import trace_tool" in cand.modified_code

    # Syntax integrity check
    parsed = ast.parse(cand.modified_code)
    assert parsed is not None


def test_scanner_skips_already_decorated_functions() -> None:
    """Verifies that functions already containing tracing decorators are skipped."""
    code = """from arc import trace_agent\n\n@trace_agent(name="main_agent")\ndef handle_message(msg: str):\n    return msg\n"""
    candidates = scan_code_for_tracing(code, filename="agent.py")
    assert len(candidates) == 0


def test_render_diff_box() -> None:
    """Verifies that render_diff_box formats changes with green/red markers."""
    code = "def process_message(msg: str):\n    return msg\n"
    candidates = scan_code_for_tracing(code, filename="service.py")
    assert len(candidates) == 1

    cand = candidates[0]
    rendered = render_diff_box(cand)
    plain = _to_plain_text(rendered)

    assert "process_message" in plain
    assert "-" in plain
    assert "+" in plain
    assert "@trace_agent" in plain
    assert "def process_message" in plain


def test_review_and_apply_candidates_accept_y(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User selecting 'y' applies modification to the target file."""
    test_file = tmp_path / "bot.py"
    test_file.write_text("def handle_message(msg: str):\n    return msg\n", encoding="utf-8")

    candidates = scan_file_for_tracing(test_file)
    assert len(candidates) == 1

    # Mock user choosing 'y'
    mock_select = MagicMock(return_value=MagicMock(ask=MagicMock(return_value="[y] Accept & Apply")))
    monkeypatch.setattr("questionary.select", mock_select)

    applied = review_and_apply_candidates(candidates, interactive=True)
    assert len(applied) == 1

    # Verify file mutated on disk
    new_content = test_file.read_text(encoding="utf-8")
    assert "@trace_agent" in new_content
    assert "def handle_message" in new_content


def test_review_and_apply_candidates_reject_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User selecting 'n' leaves the file unmodified."""
    original_code = "def handle_message(msg: str):\n    return msg\n"
    test_file = tmp_path / "bot.py"
    test_file.write_text(original_code, encoding="utf-8")

    candidates = scan_file_for_tracing(test_file)
    assert len(candidates) == 1

    # Mock user choosing 'n'
    mock_select = MagicMock(return_value=MagicMock(ask=MagicMock(return_value="[n] Reject")))
    monkeypatch.setattr("questionary.select", mock_select)

    applied = review_and_apply_candidates(candidates, interactive=True)
    assert len(applied) == 0

    # Verify file was NOT modified
    assert test_file.read_text(encoding="utf-8") == original_code


def test_review_and_apply_candidates_accept_all_a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User selecting 'a' applies all remaining candidates without prompting again."""
    file1 = tmp_path / "agent1.py"
    file1.write_text("def handle_message(msg: str):\n    return msg\n", encoding="utf-8")

    file2 = tmp_path / "tool1.py"
    file2.write_text("def lookup_user(user_id: str):\n    return user_id\n", encoding="utf-8")

    cands1 = scan_file_for_tracing(file1)
    cands2 = scan_file_for_tracing(file2)
    all_cands = cands1 + cands2
    assert len(all_cands) == 2

    # Mock user choosing 'a' on first prompt
    mock_select = MagicMock(return_value=MagicMock(ask=MagicMock(return_value="[a] Accept All")))
    monkeypatch.setattr("questionary.select", mock_select)

    applied = review_and_apply_candidates(all_cands, interactive=True)
    assert len(applied) == 2

    assert "@trace_agent" in file1.read_text(encoding="utf-8")
    assert "@trace_tool" in file2.read_text(encoding="utf-8")


def test_review_and_apply_candidates_cancel_q(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User selecting 'q' cancels immediately without further mutations."""
    file1 = tmp_path / "agent1.py"
    file1.write_text("def handle_message(msg: str):\n    return msg\n", encoding="utf-8")

    all_cands = scan_file_for_tracing(file1)

    mock_select = MagicMock(return_value=MagicMock(ask=MagicMock(return_value="[q] Cancel")))
    monkeypatch.setattr("questionary.select", mock_select)

    applied = review_and_apply_candidates(all_cands, interactive=True)
    assert len(applied) == 0
    assert "@trace_agent" not in file1.read_text(encoding="utf-8")


def test_review_and_apply_multiple_candidates_in_same_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that applying multiple candidates to the SAME file preserves all decorators."""
    code = (
        "def handle_message(msg: str):\n"
        "    return msg\n\n"
        "def lookup_order(order_id: str):\n"
        "    return order_id\n"
    )
    test_file = tmp_path / "combined.py"
    test_file.write_text(code, encoding="utf-8")

    cands = scan_file_for_tracing(test_file)
    assert len(cands) == 2

    # Accept all
    mock_select = MagicMock(return_value=MagicMock(ask=MagicMock(return_value="[a] Accept All")))
    monkeypatch.setattr("questionary.select", mock_select)

    applied = review_and_apply_candidates(cands, interactive=True)
    assert len(applied) == 2

    final_content = test_file.read_text(encoding="utf-8")
    assert "@trace_agent(name=\"handle_message\")" in final_content
    assert "@trace_tool(name=\"lookup_order\")" in final_content
    # Syntax check
    assert ast.parse(final_content) is not None


def test_scanner_rejects_false_positives() -> None:
    """Verifies that staticmethods, UI badge helpers, properties, test files, and CLI commands are never scanned."""
    code = """
class Badge:
    @staticmethod
    def agent() -> str:
        return "agent"

    @staticmethod
    def tool() -> str:
        return "tool"

    @property
    def api_key(self) -> str:
        return "key"

def main() -> None:
    pass

def test_something():
    assert True
"""
    # 1. Non-test filename
    cands = scan_code_for_tracing(code, filename="badges.py")
    assert len(cands) == 0

    # 2. Test filename ignored
    test_cands = scan_code_for_tracing(
        "def handle_message(msg): pass", filename="tests/test_agent.py"
    )
    assert len(test_cands) == 0

