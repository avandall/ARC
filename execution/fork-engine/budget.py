"""Budget Enforcer module for Fork-Replay Engine.

Tracks resource consumption (USD cost, tokens, duration) across parallel branch executions
and enforces hard budget boundaries.
"""

from __future__ import annotations

import threading
from typing import Any


class BudgetExceededException(Exception):
    """Raised when execution cost exceeds the configured budget limit."""


class BudgetEnforcer:
    """Enforces strict budget limits (USD, tokens, max execution time) across parallel runs."""

    def __init__(
        self,
        budget_usd: float | None = None,
        budget_tokens: int | None = None,
        max_seconds: float | None = None,
    ) -> None:
        self.budget_usd = budget_usd
        self.budget_tokens = budget_tokens
        self.max_seconds = max_seconds

        self._accumulated_usd: float = 0.0
        self._accumulated_tokens: int = 0
        self._accumulated_seconds: float = 0.0

        self._is_aborted: bool = False
        self._abort_reason: str | None = None
        self._lock = threading.Lock()

    @property
    def accumulated_usd(self) -> float:
        """Returns total consumed USD cost."""
        with self._lock:
            return self._accumulated_usd

    @property
    def accumulated_tokens(self) -> int:
        """Returns total consumed tokens."""
        with self._lock:
            return self._accumulated_tokens

    @property
    def accumulated_seconds(self) -> float:
        """Returns total consumed seconds."""
        with self._lock:
            return self._accumulated_seconds

    @property
    def is_aborted(self) -> bool:
        """Returns True if budget threshold was exceeded and execution was aborted."""
        with self._lock:
            return self._is_aborted

    @property
    def abort_reason(self) -> str | None:
        """Returns the reason for abort if budget was exceeded."""
        with self._lock:
            return self._abort_reason

    def record_usage(
        self,
        cost_usd: float = 0.0,
        tokens: int = 0,
        seconds: float = 0.0,
    ) -> bool:
        """Records resource usage for a completed or running branch.

        Returns True if budget limit was exceeded.
        """
        with self._lock:
            self._accumulated_usd += cost_usd
            self._accumulated_tokens += tokens
            self._accumulated_seconds += seconds

            exceeded = False
            reason = None

            if self.budget_usd is not None and self._accumulated_usd > self.budget_usd:
                exceeded = True
                reason = f"budget_usd exceeded ({self._accumulated_usd:.4f} > {self.budget_usd:.4f})"
            elif self.budget_tokens is not None and self._accumulated_tokens > self.budget_tokens:
                exceeded = True
                reason = f"budget_tokens exceeded ({self._accumulated_tokens} > {self.budget_tokens})"
            elif self.max_seconds is not None and self._accumulated_seconds > self.max_seconds:
                exceeded = True
                reason = f"max_seconds exceeded ({self._accumulated_seconds:.2f} > {self.max_seconds:.2f})"

            if exceeded:
                self._is_aborted = True
                self._abort_reason = reason or "budget_exceeded"

            return self._is_aborted

    def to_dict(self) -> dict[str, Any]:
        """Returns dictionary representation of budget status."""
        with self._lock:
            return {
                "budget_usd": self.budget_usd,
                "budget_tokens": self.budget_tokens,
                "max_seconds": self.max_seconds,
                "accumulated_usd": round(self._accumulated_usd, 4),
                "accumulated_tokens": self._accumulated_tokens,
                "accumulated_seconds": round(self._accumulated_seconds, 2),
                "is_aborted": self._is_aborted,
                "abort_reason": self._abort_reason,
            }
