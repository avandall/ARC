"""Unit tests for Regression Test Generator & GitHub Actions Workflow (TASK-P4-002)."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import yaml

from arc.execution.fork_engine.regression_generator import (
    RegressionTestGenerator,
    generate_regression_test,
)


def test_codegen_pytest_from_reproducer_yaml(tmp_path: Path) -> None:
    """Happy Path 1: Load arc-repro-8842.yaml and generate test_arc_regression_8842.py.

    Generator produces valid pytest test file containing test function calling sandbox runner
    with exact fault_spec and asserting invariant INV-PAY-002.
    """
    repro_yaml = tmp_path / "arc-repro-8842.yaml"
    repro_content = {
        "trace": "trace_8842_abc",
        "determinism_level": "L1",
        "faults": [
            {
                "at_step": 2,
                "type": "timeout_before_commit",
                "tool": "mock_payment_gateway",
                "params": {"amount": 100},
            }
        ],
        "violated": "INV-PAY-002",
        "reproduce_rate": 1.0,
        "confidence_interval": [0.90, 1.0],
        "cost_usd": 0.15,
    }
    with open(repro_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(repro_content, f)

    output_dir = tmp_path / "regression"
    generator = RegressionTestGenerator(output_dir=output_dir)
    generated_path = generator.generate_from_yaml(repro_yaml)

    assert generated_path.name == "test_arc_regression_8842.py"
    assert generated_path.exists()

    code = generated_path.read_text(encoding="utf-8")
    assert "def test_arc_regression_8842()" in code
    assert "INV-PAY-002" in code
    assert "run_sandbox_runner" in code
    assert "timeout_before_commit" in code

    # Validate AST syntax validity
    parsed_ast = ast.parse(code)
    assert parsed_ast is not None


def test_github_actions_workflow_syntax_validity() -> None:
    """Happy Path 2: Check YAML syntax validity of .github/workflows/arc-gate.yml.

    Workflow contains jobs 'smoke-gate' (PR) and 'nightly-gate', and correctly handles
    exit code 1 (block merge) and exit code 2 (warning comment).
    """
    workflow_path = Path(".github/workflows/arc-gate.yml")
    assert workflow_path.exists(), "Workflow file .github/workflows/arc-gate.yml does not exist"

    content = workflow_path.read_text(encoding="utf-8")
    parsed_yaml = yaml.safe_load(content)

    assert isinstance(parsed_yaml, dict)
    assert "jobs" in parsed_yaml
    jobs = parsed_yaml["jobs"]

    assert "smoke-gate" in jobs
    assert "nightly-gate" in jobs

    # Check PR and nightly profile commands
    assert "arc gate --profile smoke" in content
    assert "arc gate --profile full" in content

    # Check exit code handling
    assert "exit 1" in content or "exit $EXIT_CODE" in content
    assert "exit 2" in content or "EXIT_CODE -eq 2" in content
    assert "exit 3" in content or "EXIT_CODE -eq 3" in content


def test_codegen_handles_missing_optional_fields_in_repro(tmp_path: Path) -> None:
    """Edge Case 1: Reproducer file missing cost_usd or confidence_interval.

    Generator still produces valid pytest file with safe defaults.
    """
    repro_yaml = tmp_path / "arc-repro-minimal_9999.yaml"
    repro_content = {
        "trace": "trace_minimal_9999",
        "determinism_level": "L0",
        "faults": [{"at_step": 1, "type": "network_partition"}],
        "violated": "INV-SEC-001",
    }
    with open(repro_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(repro_content, f)

    output_dir = tmp_path / "regression"
    generated_path = generate_regression_test(repro_yaml, output_dir=output_dir)

    assert generated_path.exists()
    code = generated_path.read_text(encoding="utf-8")

    assert "COST_USD: float = 0.0" in code
    assert "CONFIDENCE_INTERVAL: list[float] = [0.0, 1.0]" in code
    assert "def test_arc_regression_minimal_9999()" in code

    parsed_ast = ast.parse(code)
    assert parsed_ast is not None


def test_generated_regression_test_executes_in_standard_pytest(tmp_path: Path) -> None:
    """Edge Case 2: Run pytest on generated regression test file in mock environment.

    Test executes and asserts expected results without requiring non-standard dependencies.
    """
    repro_yaml = tmp_path / "arc-repro-8842.yaml"
    repro_content = {
        "trace": "trace_8842_abc",
        "determinism_level": "L1",
        "faults": [
            {
                "at_step": 2,
                "type": "timeout_before_commit",
                "tool": "mock_payment_gateway",
                "params": {"amount": 100},
            }
        ],
        "violated": "INV-PAY-002",
        "reproduce_rate": 1.0,
        "confidence_interval": [0.90, 1.0],
        "cost_usd": 0.15,
    }
    with open(repro_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(repro_content, f)

    # Output to actual tests/regression/ or tmp_path for execution
    generated_path = generate_regression_test(repro_yaml, output_dir=tmp_path)

    # Run pytest directly against the generated test file
    res = subprocess.run(
        [sys.executable, "-m", "pytest", str(generated_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert res.returncode == 0, f"Generated test failed execution:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "passed" in res.stdout
