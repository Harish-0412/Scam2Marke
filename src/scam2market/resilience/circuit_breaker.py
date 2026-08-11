import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


class CircuitState(StrEnum):
    closed = "CLOSED"
    open = "OPEN"
    half_open = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when a protected dependency is inside its recovery window."""


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    name: str
    state: CircuitState
    failure_count: int
    opened_for_seconds: float | None


class CircuitBreaker:
    def __init__(
        self, name: str, *, failure_threshold: int = 3, recovery_seconds: float = 30
    ) -> None:
        if failure_threshold < 1 or recovery_seconds <= 0:
            raise ValueError("circuit breaker limits must be positive")
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._lock = asyncio.Lock()

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            now = monotonic()
            if self._opened_at is not None:
                elapsed = now - self._opened_at
                if elapsed < self.recovery_seconds:
                    raise CircuitOpenError(f"{self.name} circuit is open")
                if self._half_open_in_flight:
                    raise CircuitOpenError(f"{self.name} half-open probe is already running")
                self._half_open_in_flight = True
        try:
            result = await operation()
        except Exception:
            async with self._lock:
                self._half_open_in_flight = False
                self._failures += 1
                if self._failures >= self.failure_threshold:
                    self._opened_at = monotonic()
            raise
        async with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_in_flight = False
        return result

    def snapshot(self) -> CircuitSnapshot:
        now = monotonic()
        opened_for = now - self._opened_at if self._opened_at is not None else None
        if self._opened_at is None:
            state = CircuitState.closed
        elif opened_for is not None and opened_for >= self.recovery_seconds:
            state = CircuitState.half_open
        else:
            state = CircuitState.open
        return CircuitSnapshot(self.name, state, self._failures, opened_for)
