"""ARC Visual UI Engine Package (TASK-CLI-003 & TASK-CLI-004)."""

from arc.cli.ui.badges import Badge
from arc.cli.ui.diff import render_diff_box, review_and_apply_candidates
from arc.cli.ui.reporter import (
    VisualReporter,
    render_assertion_failure,
    render_code_snippet,
    render_repro_result,
    render_summary_footer,
)
from arc.cli.ui.strict_error import (
    StrictLLMFallbackBlockedError,
    intercept_llm_response,
    render_strict_llm_error,
)

__all__ = [
    "Badge",
    "StrictLLMFallbackBlockedError",
    "VisualReporter",
    "intercept_llm_response",
    "render_assertion_failure",
    "render_code_snippet",
    "render_diff_box",
    "render_repro_result",
    "render_strict_llm_error",
    "render_summary_footer",
    "review_and_apply_candidates",
]
