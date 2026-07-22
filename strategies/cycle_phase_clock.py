"""Immutable BTC cycle calendar used only by the isolated Cycle Core candidate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


PHASES = frozenset({"post_halving", "bull_peak", "bear_onset", "accumulation"})


@dataclass(frozen=True)
class CyclePhaseClock:
    """A process-local, immutable calendar of confirmed Bitcoin halvings.

    Future estimates are deliberately excluded: a phase can only move after a
    recorded halving date, never because an estimated future event was reached.
    """

    halving_dates: tuple[date, ...] = (
        date(2012, 11, 28), date(2016, 7, 9),
        date(2020, 5, 11), date(2024, 4, 20),
    )
    post_halving_end: int = 180
    bear_onset_start: int = 540
    accumulation_start: int = 900

    def __post_init__(self) -> None:
        if not (0 < self.post_halving_end < self.bear_onset_start < self.accumulation_start):
            raise ValueError("cycle bounds must satisfy 0 < post < bear < accumulation")
        if tuple(sorted(self.halving_dates)) != self.halving_dates:
            raise ValueError("halving dates must be sorted")

    def phase_at(self, when: datetime | date) -> tuple[int, str]:
        """Return days since the last confirmed halving and its frozen phase."""
        if isinstance(when, datetime):
            if when.tzinfo is None:
                raise ValueError("phase timestamp must be timezone-aware UTC")
            when = when.astimezone(timezone.utc).date()
        candidates = [event for event in self.halving_dates if event <= when]
        if not candidates:
            return -1, "unknown"
        days = (when - candidates[-1]).days
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
