#!/usr/bin/env python
"""Run the finite preregistered V8 cold-start comparison; never place orders."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.v8_xperp.bootstrap import BootstrapConfig  # noqa: E402
from execution.v8_xperp.diagnostic import compare_cold_start  # noqa: E402
from execution.v8_xperp.index_source import OKXIndexPriceSource  # noqa: E402


PREREGISTERED_STARTS = (
    datetime(2025, 11, 1, tzinfo=UTC),
    datetime(2026, 1, 1, tzinfo=UTC),
    datetime(2026, 3, 1, tzinfo=UTC),
    datetime(2026, 5, 1, tzinfo=UTC),
    datetime(2026, 7, 1, tzinfo=UTC),
)


def main() -> int:
    source = OKXIndexPriceSource(market_api=None)
    config = BootstrapConfig()

    def sample_after(at: datetime, retrieved_at: datetime):
        return source.reference_after(
            at - timedelta(microseconds=1), retrieved_at=retrieved_at
        )

    report = {
        "purpose": "diagnostic_only_no_optimization_no_order_path",
        "frozen_parameters": {
            "max_equity_loss_to_reference_pct": str(
                config.max_equity_loss_to_reference_pct
            ),
            "maximum_leverage": str(config.maximum_leverage),
            "minimum_entry_leverage": str(config.minimum_entry_leverage),
        },
        "preregistered_starts": [item.isoformat() for item in PREREGISTERED_STARTS],
        "results": [
            compare_cold_start(item, sample_after=sample_after, config=config)
            for item in PREREGISTERED_STARTS
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
