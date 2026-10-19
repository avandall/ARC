"""Solid color badge components for ARC CLI UI (TASK-CLI-003).

Provides test-runner badges (FAIL, PASS, category tags) with high contrast
on dark terminal backgrounds without emoji clutter.
"""

from __future__ import annotations


class Badge:
    """Solid color badge components."""

    @staticmethod
    def fail() -> str:
        """Returns standard FAIL badge (bold white text on red background)."""
        return "[bold white on red] FAIL [/]"

    @staticmethod
    def pass_() -> str:
        """Returns standard PASS badge (bold white text on green background)."""
        return "[bold white on green] PASS [/]"

    @staticmethod
    def tag(label: str) -> str:
        """Returns standard category badge (bold black text on yellow background)."""
        return f"[bold black on yellow] {label.strip()} [/]"

    @staticmethod
    def agent() -> str:
        """Returns agent category badge."""
        return Badge.tag("agent")

    @staticmethod
    def repro() -> str:
        """Returns repro category badge."""
        return Badge.tag("repro")

    @staticmethod
    def tool() -> str:
        """Returns tool category badge."""
        return Badge.tag("tool")

    @staticmethod
    def llm_api() -> str:
        """Returns llm-api category badge."""
        return Badge.tag("llm-api")
