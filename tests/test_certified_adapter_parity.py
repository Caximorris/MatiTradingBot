from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.certification import TargetIntent
from core.certified_adapters import run_captured
from data.market_data import OHLCVBar


def test_all_certified_modes_replay_identically():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = [OHLCVBar(int((start + timedelta(hours=i)).timestamp() * 1000), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("1")) for i in range(3)]
    class Strategy:
        def __init__(self): self.done = False
        def decide(self, snapshot):
            if self.done: return None
            self.done = True
            return TargetIntent("one", target_base_pct=Decimal("1"))
    results = [run_captured(mode, bars, Strategy(), warmup_bars=0, fee_rate=Decimal(".001"), slippage_bps=Decimal("5")) for mode in ("backtest", "replay", "report", "shadow", "paper", "live_dry_run")]
    assert all(result == results[0] for result in results)
