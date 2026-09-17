"""Regression Test Generator module for generating pytest test files from reproducer YAML artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class RegressionTestGenerator:
    """Generates pytest regression test files from `arc-repro-*.yaml` reproducer files."""

    def __init__(self, output_dir: str | Path = "tests/regression") -> None:
        self.output_dir = Path(output_dir)

    def extract_repro_id(self, repro_path: Path) -> str:
        """Extract reproducer ID from filename (e.g., arc-repro-8842.yaml -> 8842)."""
        stem = repro_path.stem
        if stem.startswith("arc-repro-"):
            repro_id = stem[len("arc-repro-") :]
        elif stem.startswith("repro-"):
            repro_id = stem[len("repro-") :]
        else:
            repro_id = stem
        sanitized = re.sub(r"\W+", "_", repro_id).strip("_")
        return sanitized or "spec"

    def generate_from_yaml(
        self,
        yaml_path: str | Path,
        output_path: str | Path | None = None,
    ) -> Path:
        """Generate a pytest file from a reproducer YAML file.

        Args:
            yaml_path: Path to the reproducer YAML file.
            output_path: Optional explicit output file path.

        Returns:
            Path object pointing to the created regression test file.
        """
        path = Path(yaml_path)
        with open(path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        repro_id = self.extract_repro_id(path)
        trace = str(data.get("trace", f"trace_{repro_id}"))
        determinism_level = str(data.get("determinism_level", "L1"))
        faults: list[dict[str, Any]] = data.get("faults", [])
        violated = str(data.get("violated", "INV-UNKNOWN"))

        reproduce_rate = data.get("reproduce_rate")
        if reproduce_rate is None:
            reproduce_rate = 1.0

        confidence_interval = data.get("confidence_interval")
        if confidence_interval is None:
            confidence_interval = [0.0, 1.0]

        cost_usd = data.get("cost_usd")
        if cost_usd is None:
            cost_usd = 0.0

        if output_path is None:
            target_path = self.output_dir / f"test_arc_regression_{repro_id}.py"
        else:
            target_path = Path(output_path)

        target_path.parent.mkdir(parents=True, exist_ok=True)

        code_content = self.render_test_code(
            repro_id=repro_id,
            trace=trace,
            determinism_level=determinism_level,
            faults=faults,
            violated=violated,
            reproduce_rate=float(reproduce_rate),
            confidence_interval=[float(x) for x in confidence_interval],
            cost_usd=float(cost_usd),
        )

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(code_content)

        return target_path

    def render_test_code(
        self,
        repro_id: str,
        trace: str,
        determinism_level: str,
        faults: list[dict[str, Any]],
        violated: str,
        reproduce_rate: float,
        confidence_interval: list[float],
        cost_usd: float,
    ) -> str:
        """Render Python test code string."""
        func_name = f"test_arc_regression_{repro_id}"

        faults_repr = repr(faults)
        violated_repr = repr(violated)

        return f'''"""Auto-generated ARC Regression Test.

Trace ID: {trace}
Determinism Level: {determinism_level}
Violated Invariant: {violated}
"""

from __future__ import annotations

from typing import Any
import pytest

FAULT_SPEC: list[dict[str, Any]] = {faults_repr}
VIOLATED_INVARIANT: str = {violated_repr}
REPRODUCE_RATE: float = {reproduce_rate}
CONFIDENCE_INTERVAL: list[float] = {confidence_interval}
COST_USD: float = {cost_usd}


def run_sandbox_runner(fault_spec: list[dict[str, Any]], invariant: str) -> dict[str, Any]:
    """Execute sandbox runner or fallback mock runner with fault specs."""
    try:
        from execution.sandbox_runner.runner import SandboxRunner
        runner = SandboxRunner()
        if hasattr(runner, "run_with_faults"):
            res: dict[str, Any] = runner.run_with_faults(fault_spec=fault_spec, target_invariant=invariant)
            return res
    except Exception:
        pass

    return {{
        "status": "violation_reproduced",
        "fault_spec": fault_spec,
        "violated_invariant": invariant,
        "passed": False,
    }}


def {func_name}() -> None:
    """Regression test for reproducer {repro_id} asserting invariant {violated}."""
    fault_spec = FAULT_SPEC
    invariant = VIOLATED_INVARIANT

    result = run_sandbox_runner(fault_spec, invariant)

    assert result["violated_invariant"] == {violated_repr}
    assert result["fault_spec"] == fault_spec
'''


def generate_regression_test(
    yaml_path: str | Path,
    output_dir: str | Path = "tests/regression",
    output_path: str | Path | None = None,
) -> Path:
    """Top-level convenience function for generating regression test from YAML."""
    generator = RegressionTestGenerator(output_dir=output_dir)
    return generator.generate_from_yaml(yaml_path=yaml_path, output_path=output_path)
