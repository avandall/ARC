"""Fault Catalog Engine models and specification registry.

Manages infrastructure (Group A) and semantic (Group B) fault injection definitions.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from enum import Enum
from typing import Any


class FaultType(str, Enum):
    """Supported fault injection types."""

    # Group A: Infrastructure Faults
    TIMEOUT_BEFORE_COMMIT = "timeout_before_commit"
    TIMEOUT_AFTER_COMMIT = "timeout_after_commit"
    HTTP_500 = "http_500"
    HTTP_502 = "http_502"
    HTTP_429 = "http_429"
    LATENCY_SPIKE = "latency_spike"

    # Group B: Semantic Faults
    BAD_SCHEMA = "bad_schema"
    REQUIRED_FIELD_NULL = "required_field_null"
    EMPTY_LIST = "empty_list"
    TYPE_COERCION = "type_coercion"
    BOUNDARY_VALUE = "boundary_value"


INFRA_FAULTS: set[str] = {
    FaultType.TIMEOUT_BEFORE_COMMIT.value,
    FaultType.TIMEOUT_AFTER_COMMIT.value,
    FaultType.HTTP_500.value,
    FaultType.HTTP_502.value,
    FaultType.HTTP_429.value,
    FaultType.LATENCY_SPIKE.value,
}

SEMANTIC_FAULTS: set[str] = {
    FaultType.BAD_SCHEMA.value,
    FaultType.REQUIRED_FIELD_NULL.value,
    FaultType.EMPTY_LIST.value,
    FaultType.TYPE_COERCION.value,
    FaultType.BOUNDARY_VALUE.value,
}


class FaultSpec:
    """Fault Specification model defining step, tool target, fault type, and parameters."""

    def __init__(
        self,
        at_step: int,
        fault_type: str | FaultType,
        target_tool: str | None = None,
        params: dict[str, Any] | None = None,
        fault_id: str | None = None,
        applied: bool = False,
    ) -> None:
        self.at_step = at_step
        self.fault_type = (
            fault_type.value if isinstance(fault_type, FaultType) else str(fault_type)
        )
        self.target_tool = target_tool
        self.params = params or {}
        self.fault_id = fault_id or f"fault_{uuid.uuid4().hex[:8]}"
        self.applied = applied

    def to_dict(self) -> dict[str, Any]:
        """Converts FaultSpec to dictionary format matching JSON schemas."""
        return {
            "fault_id": self.fault_id,
            "at_step": self.at_step,
            "type": self.fault_type,
            "tool": self.target_tool,
            "params": self.params,
            "applied": self.applied,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FaultSpec:
        """Instantiates FaultSpec from a dictionary representation."""
        at_step = int(data["at_step"])
        fault_type = data.get("type") or data.get("fault_type")
        if not fault_type:
            msg = "Fault specification requires 'type' or 'fault_type'"
            raise ValueError(msg)

        target_tool = data.get("tool") or data.get("target_tool")
        params = data.get("params") or {}
        fault_id = data.get("fault_id")
        applied = bool(data.get("applied", False))

        return cls(
            at_step=at_step,
            fault_type=fault_type,
            target_tool=target_tool,
            params=params,
            fault_id=fault_id,
            applied=applied,
        )


class FaultCatalog:
    """Registry managing single and compound fault specifications."""

    def __init__(self, specs: Sequence[FaultSpec] | None = None) -> None:
        self._specs: list[FaultSpec] = list(specs) if specs else []

    def add_fault(self, spec: FaultSpec | dict[str, Any]) -> FaultSpec:
        """Registers a fault specification into the catalog."""
        fault_spec = spec if isinstance(spec, FaultSpec) else FaultSpec.from_dict(spec)
        self._specs.append(fault_spec)
        return fault_spec

    def add_compound_faults(
        self, specs: Sequence[FaultSpec | dict[str, Any]]
    ) -> list[FaultSpec]:
        """Registers a sequential chain of compound fault specifications."""
        added: list[FaultSpec] = []
        for spec in specs:
            added.append(self.add_fault(spec))
        return added

    def get_faults_for_step(
        self, step_id: int, tool_name: str | None = None
    ) -> list[FaultSpec]:
        """Finds all applicable unapplied faults for a given step_id and optional target tool."""
        matching: list[FaultSpec] = []
        for spec in self._specs:
            if (
                spec.at_step == step_id
                and not spec.applied
                and (spec.target_tool is None or tool_name is None or spec.target_tool == tool_name)
            ):
                matching.append(spec)
        return matching

    def get_all_faults(self) -> list[FaultSpec]:
        """Returns all registered fault specifications."""
        return list(self._specs)

    def get_untriggered_faults(self) -> list[FaultSpec]:
        """Returns all fault specifications that have not been applied."""
        return [spec for spec in self._specs if not spec.applied]

    def clear(self) -> None:
        """Clears all registered fault specifications."""
        self._specs.clear()

    @classmethod
    def from_list(cls, items: Sequence[FaultSpec | dict[str, Any]]) -> FaultCatalog:
        """Creates a FaultCatalog instance from a list of fault specifications."""
        catalog = cls()
        catalog.add_compound_faults(items)
        return catalog
