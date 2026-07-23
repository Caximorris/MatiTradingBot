"""Immutable BTC cycle calendar used only by the isolated Cycle Core candidate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


PHASES = frozenset({"post_halving", "bull_peak", "bear_onset", "accumulation"})

_CONFIRMED_HALVINGS = (
    datetime(2012, 11, 28, 15, 24, 38, tzinfo=timezone.utc),
    datetime(2016, 7, 9, 16, 46, 13, tzinfo=timezone.utc),
    datetime(2020, 5, 11, 19, 23, 43, tzinfo=timezone.utc),
    datetime(2024, 4, 20, 0, 9, 27, tzinfo=timezone.utc),
)


@dataclass(frozen=True)
class CyclePhaseClock:
    """Confirmed-block calendar; estimates never change the active cycle.

    A 1H bar stamped ``t`` is considered available only at its successor's
    open.  Consequently a 4H decision at ``t`` can first use the phase active
    at ``t`` and data closed no later than ``t``.  This prevents a date-only
    midnight activation for intraday confirmed events.
    """

    halving_timestamps: tuple[datetime, ...] = _CONFIRMED_HALVINGS
    post_halving_end: int = 180
    bear_onset_start: int = 540
    accumulation_start: int = 900

    def __post_init__(self) -> None:
        if not (0 < self.post_halving_end < self.bear_onset_start < self.accumulation_start):
            raise ValueError("cycle bounds must satisfy 0 < post < bear < accumulation")
        if any(item.tzinfo is None or item.utcoffset() != timezone.utc.utcoffset(item)
               for item in self.halving_timestamps):
            raise ValueError("halving timestamps must be timezone-aware UTC")
        if tuple(sorted(self.halving_timestamps)) != self.halving_timestamps:
            raise ValueError("halving timestamps must be sorted")

    @property
    def halving_dates(self) -> tuple[date, ...]:
        """Compatibility view; callers must not use it for phase activation."""
        return tuple(item.date() for item in self.halving_timestamps)

    def phase_at(self, when: datetime | date) -> tuple[int, str]:
        """Return elapsed completed UTC days since the last confirmed block."""
        if isinstance(when, date) and not isinstance(when, datetime):
            when = datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc)
        if when.tzinfo is None:
            raise ValueError("phase timestamp must be timezone-aware UTC")
        utc = when.astimezone(timezone.utc)
        candidates = [event for event in self.halving_timestamps if event <= utc]
        if not candidates:
            return -1, "unknown"
        days = (utc - candidates[-1]).days
        if days < self.post_halving_end:
            return days, "post_halving"
        if days < self.bear_onset_start:
            return days, "bull_peak"
        if days < self.accumulation_start:
            return days, "bear_onset"
        return days, "accumulation"

    @staticmethod
    def evaluation_block(when: datetime) -> str:
        """UTC 4-hour decision block; all adapters use the same key."""
        if when.tzinfo is None:
            raise ValueError("evaluation timestamp must be timezone-aware UTC")
        utc = when.astimezone(timezone.utc)
        return f"{utc.date().isoformat()}T{utc.hour // 4}"
