"""Base ToolModel Plugin Architecture and Registry (§3.3, §7.4)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

registry: dict[str, type[ToolModel]] = {}


class UnsupportedFaultException(Exception):
    """Raised when a ToolModel receives a fault spec that it does not support."""


class ToolModel(ABC):
    """Abstract base class for stateful tool models (§3.3).

    Each K-run branch must clone its own fresh instance via `clone_fresh_state()`
    to prevent cross-branch state contamination (§7.4).
    """

    tool_name: str
    version: str

    @abstractmethod
    def clone_fresh_state(self, seed_state_ref: str = "") -> ToolModel:
        """Returns a new ToolModel instance with isolated fresh state.

        Args:
            seed_state_ref: Reference identifier for state snapshot before fork point.

        Returns:
            A new independent ToolModel instance.
        """

    @abstractmethod
    def handle(
        self,
        request_args: dict[str, Any],
        injected_fault: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handles a tool call, applying state mutations or injected faults.

        Args:
            request_args: Tool request arguments dictionary.
            injected_fault: Optional fault specification dict for chaos testing.

        Returns:
            Tool call response dictionary.

        Raises:
            UnsupportedFaultException: If injected_fault specifies an unsupported fault.
        """

    @abstractmethod
    def to_effect_ledger_entries(self) -> list[dict[str, Any]]:
        """Exports accumulated effect entries conforming to schema §4.3.

        Returns:
            List of effect dictionaries.
        """


def register(cls: type[ToolModel]) -> type[ToolModel]:
    """Decorator registering a ToolModel implementation into the global registry.

    Args:
        cls: ToolModel subclass to register.

    Returns:
        The registered class.
    """
    registry[cls.tool_name] = cls
    return cls
