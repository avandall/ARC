"""Visual UI Engine and Metrics Reporter for ARC CLI (TASK-CLI-003).

Renders test runner output in modern Playwright / Tester-Army style:
- High contrast solid color badges
- Line-numbered code snippets with caret pointers
- Structured context indentation
- Token-efficient summary footers with AI & Cache metrics
- Zero emoji clutter
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from arc.cli.ui.badges import Badge

console = Console()


def render_code_snippet(
    lines: list[tuple[int, str]],
    highlight_line: int | None = None,
    caret_col: int | None = None,
    gutter_width: int = 5,
) -> str:
    """Renders formatted code lines with gutter line numbers `126|` and caret pointers `^`."""
    output_lines: list[str] = []

    for lineno, text in lines:
        prefix = f"{lineno:>{gutter_width}}| "
        if lineno == highlight_line:
            output_lines.append(f"[bold cyan]{prefix}[/bold cyan]{text}")
            if caret_col is not None and caret_col > 0:
                gutter_space = " " * gutter_width + "| "
                caret_indent = " " * max(0, caret_col - 1)
                output_lines.append(
                    f"[bold red]{gutter_space}{caret_indent}^[/bold red]"
                )
        else:
            output_lines.append(f"[dim]{prefix}[/dim]{text}")

    return "\n".join(output_lines)


def render_assertion_failure(
    test_path: str,
    test_name: str,
    error_title: str,
    error_message: str,
    location: str,
    code_snippet: list[tuple[int, str]] | None = None,
    highlight_line: int | None = None,
    caret_col: int | None = None,
    contexts: list[str] | None = None,
    category: str = "agent",
) -> str:
    """Renders assertion failure in Playwright/Tester-Army visual format."""
    fail_badge = Badge.fail()
    category_badge = Badge.tag(category)

    parts: list[str] = [
        f" {fail_badge}   {category_badge}  [bold]{test_path}[/bold] > [dim]{test_name}[/dim]",
        f"[bold red]{error_title}:[/bold red] [red]{error_message}[/red]",
        f" [cyan]> {location}[/cyan]",
    ]

    if code_snippet:
        parts.append(
            render_code_snippet(
                code_snippet, highlight_line=highlight_line, caret_col=caret_col
            )
        )

    if contexts:
        parts.append("")
        for ctx in contexts:
            parts.append(f" [dim]> {ctx}[/dim]")

    return "\n".join(parts)


def render_summary_footer(
    total_files: int,
    failed_files: int,
    passed_files: int,
    total_tests: int,
    failed_tests: int,
    passed_tests: int,
    ai_tokens: str,
    ai_cached_pct: int | None = None,
    ai_model_calls: int = 0,
    ai_model_name: str = "gpt-4o",
    cache_replayed: int = 0,
    cache_handed_off: int = 0,
    cache_missed: int = 0,
    start_time: str | None = None,
    duration: float | str = "0.0s",
    current_iteration: int = 1,
    total_iterations: int = 1,
    line_width: int = 100,
) -> str:
    """Renders standard summary metrics footer with divider and resource counters."""
    sep_badge = f"[{current_iteration}/{total_iterations}]"
    dash_count = max(5, (line_width - len(sep_badge) - 2) // 2)
    separator = f"[dim]{'-' * dash_count} {sep_badge} {'-' * dash_count}[/dim]"

    # File stats
    files_failed_str = f"[bold red]{failed_files} failed[/bold red]" if failed_files > 0 else "0 failed"
    files_passed_str = f"[bold green]{passed_files} passed[/bold green]"
    files_line = f"Test Files  {files_failed_str} | {files_passed_str} ({total_files})"

    # Tests stats
    tests_failed_str = f"[bold red]{failed_tests} failed[/bold red]" if failed_tests > 0 else "0 failed"
    tests_passed_str = f"[bold green]{passed_tests} passed[/bold green]"
    tests_line = f"     Tests  {tests_failed_str} | {tests_passed_str} ({total_tests})"

    # AI stats
    cached_part = f"{ai_cached_pct}% cached • " if ai_cached_pct is not None else ""
    calls_part = f"{ai_model_calls} model calls • " if ai_model_calls > 0 else ""
    ai_line = f"        AI  {ai_tokens} tokens • {cached_part}{calls_part}{ai_model_name}"

    # Cache stats
    cache_line = (
        f"     Cache  {cache_replayed} replayed • {cache_handed_off} handed off • {cache_missed} missed"
    )

    duration_str = f"{duration:.2f}s" if isinstance(duration, (int, float)) else str(duration)

    footer_rows = [
        "",
        separator,
        "",
        files_line,
        tests_line,
        ai_line,
        cache_line,
    ]

    if start_time:
        footer_rows.append(f"  Start at  {start_time}")
    footer_rows.append(f"  Duration  {duration_str}")

    return "\n".join(footer_rows)


def render_repro_result(
    incident_file: str,
    target_engine: str = "Replay Engine",
    violation_type: str = "REPRODUCED_INVARIANT_VIOLATION",
    violation_title: str = "",
    invariant_id: str = "",
    invariant_type: str = "Safety",
    statement: str = "",
    mechanism: str = "",
    fault_chain: list[str] | None = None,
    evidence_diff: list[str] | None = None,
    diff_file: str | None = None,
    replay_status: str = "REPRODUCED (100% Deterministic)",
    wilson_ci: str = "[92.5%, 100.0%]",
    ai_tokens: str = "42.1k",
    ai_model_name: str = "gpt-4o",
    duration: float | str = "4.12s",
    current_iteration: int = 1,
    total_iterations: int = 1,
    line_width: int = 100,
) -> str:
    """Renders deterministic reproduction output matching Section 3.2 spec."""
    pass_badge = Badge.pass_()
    repro_badge = Badge.tag("repro")

    parts: list[str] = [
        f" {pass_badge}   {repro_badge}  [bold]{incident_file}[/bold] > [dim]{target_engine}[/dim]",
        f"[bold red]{violation_type}:[/bold red] {violation_title}",
        f" [cyan]> Violated Invariant: {invariant_id} ({invariant_type})[/cyan]",
        f" [cyan]> Statement: \"{statement}\"[/cyan]",
        f" [dim]> Mechanism: {mechanism}[/dim]",
    ]

    if fault_chain:
        parts.append("")
        parts.append(" [cyan]> Fault Chain Injected:[/cyan]")
        for item in fault_chain:
            parts.append(f"   {item}")

    if evidence_diff:
        parts.append("")
        parts.append(" [cyan]> Evidence:[/cyan]")
        for diff_line in evidence_diff:
            if diff_line.startswith("+"):
                parts.append(f"   [green]{diff_line}[/green]")
            elif diff_line.startswith("-"):
                parts.append(f"   [red]{diff_line}[/red]")
            else:
                parts.append(f"   {diff_line}")

    if diff_file:
        parts.append(f" [dim]> Diff saved: {diff_file}[/dim]")

    sep_badge = f"[{current_iteration}/{total_iterations}]"
    dash_count = max(5, (line_width - len(sep_badge) - 2) // 2)
    separator = f"[dim]{'-' * dash_count} {sep_badge} {'-' * dash_count}[/dim]"

    duration_str = f"{duration:.2f}s" if isinstance(duration, (int, float)) else str(duration)

    parts.extend([
        "",
        separator,
        "",
        f" Replay Status  [bold green]{replay_status}[/bold green]",
        f"     Wilson CI  {wilson_ci} (95% confidence interval)",
        f"            AI  {ai_tokens} tokens • {ai_model_name}",
        f"      Duration  {duration_str}",
    ])

    return "\n".join(parts)


class VisualReporter:
    """Class wrapper providing visual rendering utilities."""

    def __init__(self, console_instance: Console | None = None) -> None:
        self.console = console_instance or Console()

    def badge_fail(self) -> str:
        """Returns standard FAIL badge."""
        return Badge.fail()

    def badge_pass(self) -> str:
        """Returns standard PASS badge."""
        return Badge.pass_()

    def badge_tag(self, label: str) -> str:
        """Returns standard category badge."""
        return Badge.tag(label)

    def print_assertion_failure(self, **kwargs: Any) -> None:
        """Renders and prints assertion failure directly to console."""
        self.console.print(render_assertion_failure(**kwargs))

    def print_summary_footer(self, **kwargs: Any) -> None:
        """Renders and prints summary footer directly to console."""
        self.console.print(render_summary_footer(**kwargs))

    def print_repro_result(self, **kwargs: Any) -> None:
        """Renders and prints repro result directly to console."""
        self.console.print(render_repro_result(**kwargs))
