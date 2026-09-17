"""arc_sdk.clock: Virtual Clock & Deterministic RNG Abstraction.

Provides virtualized time and deterministic RNG state control to eliminate
non-determinism during execution and replay.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

T = TypeVar("T")


class VirtualClockError(Exception):
    """Exception raised for invalid virtual clock operations (e.g., backward drift)."""


class VirtualClock:
    """Virtual Clock for managing deterministic timeline in execution and replay sandbox."""

    def __init__(self, initial_time: datetime | str | float | None = None) -> None:
        """Initialize Virtual Clock.

        Args:
            initial_time: Start time as ISO format string, datetime object, or epoch timestamp in seconds/ms.
                          If None, defaults to current UTC time.
        """
        if initial_time is None:
            self._current_dt = datetime.now(timezone.utc)
        elif isinstance(initial_time, str):
            dt = datetime.fromisoformat(initial_time.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            self._current_dt = dt
        elif isinstance(initial_time, datetime):
            if initial_time.tzinfo is None:
                self._current_dt = initial_time.replace(tzinfo=timezone.utc)
            else:
                self._current_dt = initial_time
        elif isinstance(initial_time, (int, float)):
            self._current_dt = datetime.fromtimestamp(float(initial_time), tz=timezone.utc)
        else:
            raise TypeError(f"Invalid initial_time type: {type(initial_time)}")

    def now(self) -> datetime:
        """Get current virtual time as timezone-aware UTC datetime."""
        return self._current_dt

    def time(self) -> float:
        """Get current virtual timestamp as float seconds since epoch."""
        return self._current_dt.timestamp()

    def advance(self, delta_ms: float) -> datetime:
        """Advance the virtual clock by delta_ms milliseconds.

        Args:
            delta_ms: Milliseconds to advance forward.

        Returns:
            The updated datetime object.

        Raises:
            VirtualClockError: If delta_ms < 0 (attempting to drift backward).
        """
        if delta_ms < 0:
            raise VirtualClockError("Clock cannot drift backward in replay")

        self._current_dt += timedelta(milliseconds=float(delta_ms))
        return self._current_dt

    def sleep(self, seconds: float) -> None:
        """Simulate time sleep by advancing virtual timeline without blocking thread execution.

        Args:
            seconds: Seconds to sleep.

        Raises:
            VirtualClockError: If seconds < 0 (attempting to drift backward).
        """
        if seconds < 0:
            raise VirtualClockError("Clock cannot drift backward in replay")
        self.advance(seconds * 1000.0)


class DeterministicRNG:
    """Wrapper around Python's random.Random for reproducible pseudo-random number generation."""

    def __init__(self, seed: int = 42) -> None:
        """Initialize Deterministic RNG with given seed."""
        self._seed_val = seed
        self._rng = random.Random(seed)

    def seed(self, seed: int = 42) -> None:
        """Reset internal RNG state with new or default seed."""
        self._seed_val = seed
        self._rng = random.Random(seed)

    def random(self) -> float:
        """Return next random float in range [0.0, 1.0)."""
        return self._rng.random()

    def randint(self, a: int, b: int) -> int:
        """Return random integer N such that a <= N <= b."""
        return self._rng.randint(a, b)

    def uniform(self, a: float, b: float) -> float:
        """Get a random number in range [a, b)."""
        return self._rng.uniform(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        """Choose a random element from a non-empty sequence."""
        return self._rng.choice(seq)

    def sample(self, population: Sequence[T], k: int) -> list[T]:
        """Return a k length list of unique elements chosen from the population sequence."""
        return self._rng.sample(population, k)

    def get_sequence(self, n: int) -> list[float]:
        """Utility to generate a sequence of n random floats."""
        return [self.random() for _ in range(n)]


def pin_model_params(params: dict[str, Any] | None = None, seed: int = 42) -> dict[str, Any]:
    """Pin model parameters for deterministic request execution and replay.

    Sets temperature=0.0 and seed=42 in model parameters dict.
    """
    pinned = dict(params) if params is not None else {}
    pinned["temperature"] = 0.0
    pinned["seed"] = seed
    return pinned
