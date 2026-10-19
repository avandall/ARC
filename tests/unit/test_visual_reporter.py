"""Unit tests for Visual UI Engine & Metrics Reporter (TASK-CLI-003).

Covers:
- Solid color badges (FAIL, PASS, tag badges)
- render_assertion_failure() matching Playwright/Tester-Army spec
- Code snippet rendering with line numbers `126|` and caret `^`
- render_summary_footer() metrics formatting
- render_repro_result() reproduction output
- Zero emoji clutter validation
"""

import re

from rich.console import Console

from arc.cli.ui.badges import Badge
from arc.cli.ui.reporter import (
    VisualReporter,
    render_assertion_failure,
    render_code_snippet,
    render_repro_result,
    render_summary_footer,
)


def _to_plain_text(rich_str: str) -> str:
    """Renders a Rich markup string to plain text without ANSI codes."""
    console = Console(record=True, width=120, force_terminal=False)
    console.print(rich_str)
    return console.export_text()


def test_badges_markup() -> None:
    """Verifies badge styling definitions."""
    fail_badge = Badge.fail()
    pass_badge = Badge.pass_()
    agent_badge = Badge.tag("agent")
    repro_badge = Badge.tag("repro")

    assert "bold white on red" in fail_badge
    assert "FAIL" in fail_badge

    assert "bold white on green" in pass_badge
    assert "PASS" in pass_badge

    assert "bold black on yellow" in agent_badge
    assert "agent" in agent_badge

    assert "repro" in repro_badge


def test_render_code_snippet_with_caret() -> None:
    """Verifies code snippet format with line numbers and caret pointer."""
    lines = [
        (82, "// Step 3: Simulate network timeout on gateway"),
        (83, "await chaos.inject('payment_gateway', { fault: 'timeout_after_commit' });"),
        (84, "await agent.retry();"),
        (85, "expect(agent.effects.filter('payment_charge')).toHaveLength(1);"),
    ]

    rendered = render_code_snippet(lines, highlight_line=84, caret_col=7)
    plain = _to_plain_text(rendered)

    assert "82|" in plain
    assert "83|" in plain
    assert "84|" in plain
    assert "85|" in plain
    assert "^" in plain
    assert "|" in plain


def test_render_assertion_failure() -> None:
    """Verifies render_assertion_failure matches 3.1 mockup."""
    snippet = [
        (82, "// Step 3: Simulate network timeout on gateway"),
        (83, "await chaos.inject('payment_gateway', { fault: 'timeout_after_commit' });"),
        (84, "await agent.retry();"),
        (85, "expect(agent.effects.filter('payment_charge')).toHaveLength(1);"),
    ]
    contexts = [
        "at http://localhost:8089/ (ARC Debugger Proxy)",
        "backend 1 timeout (504), 1 duplicate mutation detected",
        "trace .arc/evidence/agent_faults/trace_checkout_fail_9981.json",
    ]

    markup = render_assertion_failure(
        test_path="tests/e2e/checkout_payment.e2e.ts",
        test_name="Order & Payment Flow > TC02 - Double Payment Idempotency",
        error_title="ASSERTION_FAILED",
        error_message="The agent retried payment tool without an idempotency_key after network timeout.",
        location="tests/e2e/checkout_payment.e2e.ts:84:7",
        code_snippet=snippet,
        highlight_line=84,
        caret_col=7,
        contexts=contexts,
        category="agent",
    )

    plain = _to_plain_text(markup)

    # Verify key sections
    assert "FAIL" in plain
    assert "agent" in plain
    assert "tests/e2e/checkout_payment.e2e.ts" in plain
    assert "ASSERTION_FAILED" in plain
    assert "idempotency_key after network timeout" in plain
    assert "> tests/e2e/checkout_payment.e2e.ts:84:7" in plain
    assert "84|" in plain
    assert "^" in plain
    assert "> at http://localhost:8089/ (ARC Debugger Proxy)" in plain
    assert "> trace .arc/evidence/agent_faults/trace_checkout_fail_9981.json" in plain

    # Strict: No emojis allowed
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff]", flags=re.UNICODE)
    assert not emoji_pattern.search(plain), "Emojis detected in assertion failure output!"


def test_render_summary_footer() -> None:
    """Verifies render_summary_footer matches 3.1 mockup."""
    markup = render_summary_footer(
        total_files=1,
        failed_files=1,
        passed_files=0,
        total_tests=4,
        failed_tests=1,
        passed_tests=3,
        ai_tokens="84.2k",
        ai_cached_pct=28,
        ai_model_calls=14,
        ai_model_name="gpt-4o",
        cache_replayed=9,
        cache_handed_off=2,
        cache_missed=3,
        start_time="14:22:10",
        duration="18.42s",
        current_iteration=1,
        total_iterations=1,
    )

    plain = _to_plain_text(markup)

    assert "[1/1]" in plain
    assert "Test Files" in plain
    assert "1 failed | 0 passed (1)" in plain
    assert "Tests" in plain
    assert "1 failed | 3 passed (4)" in plain
    assert "AI" in plain
    assert "84.2k tokens" in plain
    assert "28% cached" in plain
    assert "14 model calls" in plain
    assert "gpt-4o" in plain
    assert "Cache" in plain
    assert "9 replayed" in plain
    assert "2 handed off" in plain
    assert "3 missed" in plain
    assert "Start at" in plain
    assert "14:22:10" in plain
    assert "Duration" in plain
    assert "18.42s" in plain


def test_render_repro_result() -> None:
    """Verifies render_repro_result matches 3.2 mockup."""
    fault_chain = [
        "Step 3 | payment_gateway | timeout_after_commit | 504 Gateway Timeout"
    ]
    evidence_diff = [
        "- Expected: effects.count('issue_payment') == 1",
        "+ Actual:   effects.count('issue_payment') == 2",
    ]

    markup = render_repro_result(
        incident_file=".arc/incidents/inc_2026_09_payment_timeout.yaml",
        target_engine="Replay Engine",
        violation_type="REPRODUCED_INVARIANT_VIOLATION",
        violation_title="Invariant INV-PAY-002 violated at Step 3",
        invariant_id="INV-PAY-002",
        invariant_type="Safety",
        statement="Payment tool must never be executed more than once per order_id",
        mechanism="Network timeout occurred AFTER commit. Agent retried without idempotency_key.",
        fault_chain=fault_chain,
        evidence_diff=evidence_diff,
        diff_file=".arc/evidence/agent_faults/diff_inc_2026_09.diff",
        wilson_ci="[92.5%, 100.0%]",
        ai_tokens="42.1k",
        ai_model_name="gpt-4o",
        duration="4.12s",
    )

    plain = _to_plain_text(markup)

    assert "PASS" in plain
    assert "repro" in plain
    assert "REPRODUCED_INVARIANT_VIOLATION" in plain
    assert "INV-PAY-002" in plain
    assert "Safety" in plain
    assert "Fault Chain Injected" in plain
    assert "Step 3 | payment_gateway | timeout_after_commit | 504 Gateway Timeout" in plain
    assert "Evidence" in plain
    assert "Expected: effects.count('issue_payment') == 1" in plain
    assert "Actual:   effects.count('issue_payment') == 2" in plain
    assert "Replay Status" in plain
    assert "REPRODUCED (100% Deterministic)" in plain
    assert "Wilson CI" in plain
    assert "[92.5%, 100.0%]" in plain
    assert "42.1k tokens • gpt-4o" in plain
    assert "4.12s" in plain


def test_visual_reporter_instance() -> None:
    """Verifies VisualReporter class convenience methods."""
    reporter = VisualReporter()
    assert reporter is not None

    fail_badge = reporter.badge_fail()
    assert "FAIL" in fail_badge
