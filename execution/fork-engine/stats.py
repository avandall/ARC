"""Wilson Score Confidence Interval & K-runs statistical utility module.

Computes valid sample size N_valid, minimum sample size threshold N_min,
and 95% Wilson Score Interval for violated invariants across parallel fork-replay runs.
"""

from __future__ import annotations

import math
from typing import Any


def compute_n_min(k: int) -> int:
    """Computes minimum required valid sample size N_min for K parallel runs.

    Formula: N_min = max(10, ceil(0.6 * K))
    """
    if k <= 0:
        return 0
    return max(10, math.ceil(0.6 * k))


def compute_n_valid(
    k: int,
    n_miss: int = 0,
    n_infra: int = 0,
    n_budget: int = 0,
) -> int:
    """Computes valid sample size N_valid from total K runs and aborted branch counts.

    Formula: N_valid = K - (N_miss + N_infra + N_budget)
    Cancelled/aborted branches do not count as invariant violations.
    """
    return max(0, k - (n_miss + n_infra + n_budget))


def calculate_wilson_score(
    violations: int,
    n_valid: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Calculates Wilson Score Confidence Interval [CI_lower, CI_upper] for a given proportion.

    Args:
        violations: Number of branches violating the invariant.
        n_valid: Total valid sample size (N_valid).
        confidence: Confidence level (default 0.95 for 95% CI).

    Returns:
        Tuple of (CI_lower, CI_upper) rounded to 3 decimal places.
    """
    if n_valid <= 0 or violations < 0:
        return (0.0, 0.0)

    # Bound violations to n_valid
    violations = min(violations, n_valid)

    # Determine z-score based on confidence level
    try:
        from scipy import stats  # type: ignore[import-untyped]

        z = float(stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    except (ImportError, AttributeError, ValueError):
        # Fallback z-scores for common confidence levels
        if abs(confidence - 0.95) < 1e-3:
            z = 1.959963984540054
        elif abs(confidence - 0.99) < 1e-3:
            z = 2.5758293035489004
        elif abs(confidence - 0.90) < 1e-3:
            z = 1.6448536269514722
        else:
            z = 1.959963984540054

    p_hat = violations / n_valid
    z_sq = z**2
    denom = 1.0 + z_sq / n_valid

    center = (p_hat + z_sq / (2.0 * n_valid)) / denom
    spread = (z / denom) * math.sqrt(
        (p_hat * (1.0 - p_hat)) / n_valid + z_sq / (4.0 * (n_valid**2))
    )

    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)

    return (round(lower, 3), round(upper, 3))


def is_sample_sufficient(n_valid: int, k: int) -> bool:
    """Checks whether valid sample size N_valid meets minimum threshold N_min."""
    n_min = compute_n_min(k)
    return n_valid >= n_min


def summarize_stat_results(
    k: int,
    branch_outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarizes statistical outcomes across parallel branch runs."""
    n_miss = sum(1 for b in branch_outcomes if b.get("status") == "cassette_miss")
    n_infra = sum(1 for b in branch_outcomes if b.get("status") in ("infra_error", "timeout"))
    n_budget = sum(1 for b in branch_outcomes if b.get("status") == "budget_aborted")

    n_valid = compute_n_valid(k, n_miss=n_miss, n_infra=n_infra, n_budget=n_budget)
    n_min = compute_n_min(k)
    sufficient = n_valid >= n_min

    # Aggregate violations by invariant_id
    violation_counts: dict[str, int] = {}
    for b in branch_outcomes:
        if b.get("status") == "success" and b.get("violations"):
            for inv_id in b.get("violations", []):
                violation_counts[inv_id] = violation_counts.get(inv_id, 0) + 1

    violations_summary: dict[str, dict[str, Any]] = {}
    if sufficient and n_valid > 0:
        for inv_id, count in violation_counts.items():
            ci_lower, ci_upper = calculate_wilson_score(count, n_valid)
            rate = round(count / n_valid, 3)
            violations_summary[inv_id] = {
                "hits": count,
                "n_valid": n_valid,
                "violation_rate": rate,
                "wilson_ci": [ci_lower, ci_upper],
            }

    return {
        "k": k,
        "n_valid": n_valid,
        "n_min": n_min,
        "n_miss": n_miss,
        "n_infra": n_infra,
        "n_budget": n_budget,
        "is_sufficient": sufficient,
        "violations": violations_summary,
    }
