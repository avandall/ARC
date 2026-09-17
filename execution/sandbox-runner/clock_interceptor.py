"""clock_interceptor.py: System clock interceptor for sandbox execution environment."""

from __future__ import annotations

import datetime
import time
import types
from collections.abc import Generator
from contextlib import contextmanager

from arc_sdk.clock import VirtualClock
from typing_extensions import Self


class FakeDatetime(datetime.datetime):
    """Subclass of datetime.datetime that redirects now() and utcnow() to VirtualClock."""

    _virtual_clock: VirtualClock | None = None

    @classmethod
    def now(cls, tz: datetime.tzinfo | None = None) -> datetime.datetime:  # type: ignore[override]
        if cls._virtual_clock is not None:
            v_now = cls._virtual_clock.now()
            if tz is not None:
                return v_now.astimezone(tz)  # type: ignore[no-any-return]
            return v_now  # type: ignore[no-any-return]
        return super().now(tz)  # type: ignore[no-any-return]

    @classmethod
    def utcnow(cls) -> datetime.datetime:  # type: ignore[override]
        if cls._virtual_clock is not None:
            return cls._virtual_clock.now()  # type: ignore[no-any-return]
        return super().utcnow()  # type: ignore[no-any-return]


class ClockInterceptor:
    """Context manager for intercepting time.time, time.sleep, and datetime.datetime.now."""

    def __init__(self, clock: VirtualClock) -> None:
        self.clock = clock
        self._orig_time = time.time
        self._orig_sleep = time.sleep
        self._orig_datetime = datetime.datetime

    def __enter__(self) -> Self:
        FakeDatetime._virtual_clock = self.clock

        # Monkeypatch time.time and time.sleep
        time.time = self.clock.time  # type: ignore[assignment]
        time.sleep = self.clock.sleep  # type: ignore[assignment]

        # Monkeypatch datetime.datetime in datetime module
        datetime.datetime = FakeDatetime  # type: ignore[misc]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        time.time = self._orig_time  # type: ignore[assignment]
        time.sleep = self._orig_sleep  # type: ignore[assignment]
        datetime.datetime = self._orig_datetime  # type: ignore[misc]
        FakeDatetime._virtual_clock = None


@contextmanager
def intercept_system_clock(clock: VirtualClock) -> Generator[ClockInterceptor, None, None]:
    """Helper context manager to intercept system clock functions with given VirtualClock."""
    interceptor = ClockInterceptor(clock)
    with interceptor:
        yield interceptor
