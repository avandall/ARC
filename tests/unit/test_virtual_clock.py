"""Unit tests for Virtual Clock and Deterministic RNG Abstraction (TASK-P1-001)."""

import datetime
import importlib
import time
from datetime import timezone

import pytest
from arc_sdk.clock import (
    DeterministicRNG,
    VirtualClock,
    VirtualClockError,
    pin_model_params,
)

# Load clock_interceptor dynamically from execution/sandbox-runner/clock_interceptor.py
clock_interceptor_module = importlib.import_module("execution.sandbox-runner.clock_interceptor")
ClockInterceptor = clock_interceptor_module.ClockInterceptor
intercept_system_clock = clock_interceptor_module.intercept_system_clock


def test_virtual_clock_advance_and_freeze() -> None:
    """Happy Path 1: Initialize Virtual Clock at 2026-09-14T09:00:00Z, advance by 5000ms.

    Verify clock.now() returns exactly 2026-09-14T09:00:05Z.
    """
    clock = VirtualClock("2026-09-14T09:00:00Z")
    assert clock.now() == datetime.datetime(2026, 9, 14, 9, 0, 0, tzinfo=timezone.utc)

    clock.advance(5000)

    expected = datetime.datetime(2026, 9, 14, 9, 0, 5, tzinfo=timezone.utc)
    assert clock.now() == expected
    assert clock.now().isoformat().replace("+00:00", "Z") == "2026-09-14T09:00:05Z"


def test_deterministic_rng_seed_sequence() -> None:
    """Happy Path 2: Seed RNG with seed=42. Draw 10 numbers. Reset seed=42 and draw again.

    Results must be 100% identical across runs.
    """
    rng = DeterministicRNG(seed=42)
    seq1 = rng.get_sequence(10)

    rng.seed(42)
    seq2 = rng.get_sequence(10)

    assert seq1 == seq2
    assert len(seq1) == 10

    # Test choice & randint reproducibility
    rng1 = DeterministicRNG(seed=123)
    choice1 = [rng1.randint(1, 100) for _ in range(5)]

    rng2 = DeterministicRNG(seed=123)
    choice2 = [rng2.randint(1, 100) for _ in range(5)]

    assert choice1 == choice2


def test_virtual_clock_intercepts_time_sleep() -> None:
    """Edge Case 1: Intercept time.sleep(10).

    Harness sleep does not block real thread for 10s, but immediately adds 10,000ms to virtual timeline
    and completes in < 1ms real time.
    """
    clock = VirtualClock("2026-09-14T09:00:00Z")
    start_v = clock.now()
    start_real = time.perf_counter()

    with intercept_system_clock(clock):
        time.sleep(10)
        current_time = time.time()
        current_dt = datetime.datetime.now(timezone.utc)

    elapsed_real = time.perf_counter() - start_real

    # Real time spent must be < 0.1s (much less than 10s)
    assert elapsed_real < 0.1

    # Virtual time advanced by 10s (10,000 ms)
    expected_v = datetime.datetime(2026, 9, 14, 9, 0, 10, tzinfo=timezone.utc)
    assert clock.now() == expected_v
    assert (clock.now() - start_v).total_seconds() == 10.0
    assert current_time == clock.time()
    assert current_dt == clock.now()


def test_system_clock_drift_backward_protection() -> None:
    """Edge Case 2: Attempting to set or advance time backward (negative delta).

    Raises VirtualClockError("Clock cannot drift backward in replay").
    """
    clock = VirtualClock("2026-09-14T09:00:00Z")

    with pytest.raises(VirtualClockError, match="Clock cannot drift backward in replay"):
        clock.advance(-1000)

    with pytest.raises(VirtualClockError, match="Clock cannot drift backward in replay"):
        clock.sleep(-5)


def test_pin_model_params() -> None:
    """Verify pin_model_params overrides temperature=0.0 and seed=42."""
    params = {"model": "gemini-2.5-flash", "temperature": 0.7, "top_p": 0.9}
    pinned = pin_model_params(params)

    assert pinned["temperature"] == 0.0
    assert pinned["seed"] == 42
    assert pinned["model"] == "gemini-2.5-flash"
    assert pinned["top_p"] == 0.9
    # Ensure original dict was not mutated
    assert params["temperature"] == 0.7
