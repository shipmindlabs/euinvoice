"""Invoice numbers: per-series, per-period counters that cannot skip or repeat."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Protocol, runtime_checkable

__all__ = [
    "CounterKey",
    "CounterStore",
    "InMemoryCounterStore",
    "IssuedNumber",
    "NumberSeries",
    "NumberingError",
    "Period",
    "SequentialNumbering",
]


class NumberingError(RuntimeError):
    """Raised when a counter store breaks the gapless sequence."""


class Period(Enum):
    """How long a counter runs before it restarts at one."""

    CONTINUOUS = "continuous"
    YEARLY = "yearly"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"

    def token(self, on: date) -> str:
        """The part of a number that names the period ``on`` falls in."""
        if self is Period.YEARLY:
            return f"{on.year:04d}"
        if self is Period.QUARTERLY:
            return f"{on.year:04d}Q{(on.month - 1) // 3 + 1}"
        if self is Period.MONTHLY:
            return f"{on.year:04d}{on.month:02d}"
        return ""


@dataclass(frozen=True, slots=True)
class CounterKey:
    """The counter a number is drawn from: one series in one period."""

    series: str
    period: str

    def __str__(self) -> str:
        return f"{self.series}:{self.period}" if self.period else self.series


@dataclass(frozen=True, slots=True)
class NumberSeries:
    """A family of invoice numbers and the shape they are printed in."""

    prefix: str
    period: Period = Period.YEARLY
    padding: int = 4
    separator: str = "-"

    def __post_init__(self) -> None:
        if not isinstance(self.prefix, str):
            raise TypeError("prefix must be a string")
        prefix = self.prefix.strip()
        if not prefix:
            raise ValueError("prefix must not be empty")
        object.__setattr__(self, "prefix", prefix)

        if not isinstance(self.period, Period):
            raise TypeError("period must be a Period")

        if isinstance(self.padding, bool) or not isinstance(self.padding, int):
            raise TypeError("padding must be an int")
        if not 1 <= self.padding <= 12:
            raise ValueError("padding must be between 1 and 12")

        if not isinstance(self.separator, str):
            raise TypeError("separator must be a string")

    def key_for(self, on: date) -> CounterKey:
        """The counter that a number issued on ``on`` must come from."""
        if not isinstance(on, date):
            raise TypeError("issue date must be a date")
        return CounterKey(self.prefix, self.period.token(on))

    def format(self, counter: int, on: date) -> str:
        """Render ``counter`` as a number of this series."""
        parts = [self.prefix]
        token = self.period.token(on)
        if token:
            parts.append(token)
        parts.append(f"{counter:0{self.padding}d}")
        return self.separator.join(parts)


@dataclass(frozen=True, slots=True)
class IssuedNumber:
    """A number and the counter position it was taken from."""

    number: str
    key: CounterKey
    counter: int
    issue_date: date

    def __str__(self) -> str:
        return self.number


@runtime_checkable
class CounterStore(Protocol):
    """The port that owns the counters.

    ``next_count`` returns the stored count for ``key`` plus one, starting at
    one for a key it has never seen, and never hands the same value out twice.
    The caller supplies the implementation and therefore owns the transaction:
    running the counter update and the invoice insert together is what makes
    the sequence gapless when the caller rolls back.
    """

    def next_count(self, key: CounterKey) -> int: ...


class InMemoryCounterStore:
    """Counters held in a dict, for tests and single-process use."""

    def __init__(self, counts: Mapping[CounterKey, int] | None = None) -> None:
        self._counts: dict[CounterKey, int] = dict(counts or {})
        self._lock = threading.Lock()

    def next_count(self, key: CounterKey) -> int:
        with self._lock:
            value = self._counts.get(key, 0) + 1
            self._counts[key] = value
            return value

    def current(self, key: CounterKey) -> int:
        """The last count handed out for ``key``, zero if there was none."""
        with self._lock:
            return self._counts.get(key, 0)


class SequentialNumbering:
    """Draws numbers from a series, one counter per period.

    Every value the store returns is checked against the one before it, so a
    store that skips or repeats is reported instead of silently producing a
    sequence that no tax office will accept.
    """

    def __init__(self, series: NumberSeries, store: CounterStore) -> None:
        if not isinstance(series, NumberSeries):
            raise TypeError("series must be a NumberSeries")
        if not isinstance(store, CounterStore):
            raise TypeError("store must implement next_count(key)")
        self._series = series
        self._store = store
        self._last: dict[CounterKey, int] = {}

    @property
    def series(self) -> NumberSeries:
        return self._series

    def next_number(self, issue_date: date) -> IssuedNumber:
        """Take the next number for the period ``issue_date`` falls in."""
        key = self._series.key_for(issue_date)
        counter = self._store.next_count(key)

        if isinstance(counter, bool) or not isinstance(counter, int):
            raise NumberingError(
                f"the counter store returned {counter!r} for {key}, not an int"
            )
        if counter < 1:
            raise NumberingError(f"counters start at 1, {key} returned {counter}")
        previous = self._last.get(key)
        if previous is not None and counter != previous + 1:
            raise NumberingError(
                f"{key} went from {previous} to {counter}; "
                "a sequence may neither skip nor repeat"
            )
        self._last[key] = counter

        return IssuedNumber(
            number=self._series.format(counter, issue_date),
            key=key,
            counter=counter,
            issue_date=issue_date,
        )
