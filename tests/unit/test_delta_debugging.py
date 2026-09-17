"""Unit tests for Delta Debugging (`ddmin`) and Minimal Reproducer Export."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

sys.path.insert(0, os.path.abspath("execution/fork-engine"))

from delta_debugging import IrreproducibleBugError, ddmin
from reproducer_export import export_minimal_reproducer_yaml


def test_ddmin_reduces_multi_fault_sequence() -> None:
    """Happy Path 1: Input 6 faults F=[f1, f2, f3, f4, f5, f6], only pair {f2, f5} causes failure.

    ddmin narrows down to exact minimal subset {f2, f5}.
    """
    faults = [
        {"at_step": 1, "type": "timeout_before_commit", "tool": "payment"},
        {"at_step": 2, "type": "timeout_after_commit", "tool": "refund"},
        {"at_step": 3, "type": "http_500", "tool": "inventory"},
        {"at_step": 4, "type": "latency_spike", "tool": "shipping"},
        {"at_step": 5, "type": "bad_schema_null_field", "tool": "user"},
        {"at_step": 6, "type": "http_429", "tool": "notification"},
    ]

    # Target pair: fault at step 2 (f2) and fault at step 5 (f5)
    f2 = faults[1]
    f5 = faults[4]

    def test_fn(sub: list[dict]) -> bool:
        # Failure occurs if and only if both f2 and f5 are present in sub
        return f2 in sub and f5 in sub

    minimal_faults = ddmin(faults, test_fn)

    assert len(minimal_faults) == 2
    assert f2 in minimal_faults
    assert f5 in minimal_faults


def test_export_minimal_reproducer_yaml(tmp_path: Path) -> None:
    """Happy Path 2: Export arc-repro-*.yaml and verify structure has all required fields."""
    trace_id = "trc_9988776655"
    minimal_faults = [
        {"at_step": 2, "type": "timeout_after_commit", "tool": "refund", "params": None},
        {"at_step": 5, "type": "bad_schema_null_field", "tool": "user", "params": None},
    ]
    violated_inv = "financial.no_double_refund"
    output_file = tmp_path / "arc-repro-test.yaml"

    exported_path = export_minimal_reproducer_yaml(
        trace=trace_id,
        faults=minimal_faults,
        violated=violated_inv,
        determinism_level="L1",
        reproduce_rate=0.85,
        confidence_interval=[0.65, 0.95],
        cost_usd=0.15,
        output_path=output_file,
    )

    assert exported_path.exists()

    with open(exported_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Verify required keys in YAML structure
    assert data["trace"] == trace_id
    assert data["determinism_level"] == "L1"
    assert data["faults"] == minimal_faults
    assert data["violated"] == violated_inv
    assert data["reproduce_rate"] == 0.85
    assert data["confidence_interval"] == [0.65, 0.95]
    assert data["cost_usd"] == 0.15

    # Validate against JSON schema reproducer_v1.json
    schema_path = Path("schemas/json/reproducer_v1.json")
    if schema_path.exists():
        with open(schema_path, encoding="utf-8") as sf:
            schema = json.load(sf)
        jsonschema.validate(instance=data, schema=schema)

    # Verify compatibility with `arc repro` CLI command
    from cli.commands.repro import repro_command

    repro_command(str(exported_path))


def test_ddmin_empty_fault_sequence() -> None:
    """Edge Case 1: Running ddmin with [] returns [] immediately without infinite loop."""

    def test_fn(sub: list[dict]) -> bool:
        return False

    result = ddmin([], test_fn)
    assert result == []


def test_ddmin_irreproducible_bug_handling() -> None:
    """Edge Case 2: Bug not reproducible even with full fault sequence raises IrreproducibleBugError."""
    faults = [
        {"at_step": 1, "type": "timeout_before_commit"},
        {"at_step": 2, "type": "http_500"},
    ]

    def test_fn(sub: list[dict]) -> bool:
        # Always returns False (flaky or false positive)
        return False

    with pytest.raises(IrreproducibleBugError, match="irreproducible"):
        ddmin(faults, test_fn)
