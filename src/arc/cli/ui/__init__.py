"""ARC Visual UI Engine Package (TASK-CLI-003)."""

from arc.cli.ui.badges import Badge
from arc.cli.ui.reporter import (
    VisualReporter,
    render_assertion_failure,
    render_code_snippet,
    render_repro_result,
    render_summary_footer,
)

__all__ = [
    "Badge",
    "VisualReporter",
    "render_assertion_failure",
    "render_code_snippet",
    "render_repro_result",
    "render_summary_footer",
]
