"""Reproducer export module for generating `arc-repro-*.yaml` artifact files."""

import uuid
from pathlib import Path
from typing import Any

import yaml


def export_minimal_reproducer_yaml(
    trace: str,
    faults: list[dict[str, Any]],
    violated: str,
    determinism_level: str = "L1",
    reproduce_rate: float | None = 1.0,
    confidence_interval: list[float] | None = None,
    cost_usd: float | None = 0.0,
    output_path: str | Path | None = None,
) -> Path:
    """Export a minimal reproducer artifact in YAML format conforming to §4.6 / reproducer_v1.json schema.

    Args:
        trace: Trace ID associated with the bug.
        faults: Minimal list of fault specifications (dicts).
        violated: Name or expression of the violated invariant.
        determinism_level: Determinism classification level (default "L1").
        reproduce_rate: Empirical reproduce rate (0.0 to 1.0).
        confidence_interval: Wilson score confidence interval [ci_lower, ci_upper].
        cost_usd: Total USD cost incurred during reduction/fork run.
        output_path: Target path to save the YAML file. If None, generates `arc-repro-<uuid[:8]>.yaml`.

    Returns:
        Path object pointing to the written YAML file.
    """
    if output_path is None:
        repro_id = uuid.uuid4().hex[:8]
        file_path = Path(f"arc-repro-{repro_id}.yaml")
    else:
        file_path = Path(output_path)

    reproducer_data: dict[str, Any] = {
        "trace": trace,
        "determinism_level": determinism_level,
        "faults": faults,
        "violated": violated,
        "reproduce_rate": reproduce_rate,
        "confidence_interval": confidence_interval,
        "cost_usd": cost_usd,
    }

    # Ensure parent directory exists if path contains directories
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(reproducer_data, f, sort_keys=False, default_flow_style=False)

    return file_path
