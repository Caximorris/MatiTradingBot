"""Tool-neutral, standalone reproduction of the frozen V7 calendar rule.

It intentionally imports neither the normal backtest engine nor the certified
execution engine.  The only input is a canonical OHLCV export plus this small,
declarative specification.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

UTC = timezone.utc
QTY = Decimal("0.00000001")


@dataclass(frozen=True)
class Bar:
    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Spec:
    initial_cash: str = "10000"
    fee_rate: str = "0.001"
    slippage_bps: str = "5"
    warmup_bars: int = 6000
    decision_interval_hours: int = 4
    phase_post_end: int = 180
    phase_bear_start: int = 540
    phase_accumulation_start: int = 900
    halvings: tuple[str, ...] = (
        "2012-11-28T15:24:38Z", "2016-07-09T16:46:13Z",
        "2020-05-11T19:23:43Z", "2024-04-20T00:09:27Z",
    )


def normalize(rows: list[Bar]) -> list[Bar]:
    """Stable exact-duplicate normalization; conflicts and disorder fail closed."""
    result: list[Bar] = []
    for bar in rows:
        if result and bar.timestamp == result[-1].timestamp:
            if bar != result[-1]:
                raise ValueError("conflicting duplicate candle")
            continue
        if result and bar.timestamp < result[-1].timestamp:
            raise ValueError("non-monotonic candle timestamp")
        result.append(bar)
    return result


def load_canonical(path: Path, start: datetime, end: datetime) -> list[Bar]:
    raw = json.loads(path.read_text(encoding="utf-8"))["bars"]
    rows = [Bar(int(row[0]), *(Decimal(str(value)) for value in row[1:])) for row in raw]
    lo, hi = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    return normalize([row for row in rows if lo <= row.timestamp <= hi])


def _phase(at: datetime, spec: Spec) -> tuple[int, str]:
    halvings = [datetime.fromisoformat(item.replace("Z", "+00:00")) for item in spec.halvings]
    prior = [item for item in halvings if item <= at]
    if not prior:
        raise ValueError("unconfirmed halving")
    days = (at - prior[-1]).days
    if days < spec.phase_post_end:
        return days, "post_halving"
    if days < spec.phase_bear_start:
        return days, "bull_peak"
    if days < spec.phase_accumulation_start:
        return days, "bear_onset"
    return days, "accumulation"


def run(bars: list[Bar], spec: Spec = Spec()) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if len(bars) <= spec.warmup_bars + 1:
        raise ValueError("insufficient bars")
    cash, btc = Decimal(spec.initial_cash), Decimal("0")
    fee_rate, bps = Decimal(spec.fee_rate), Decimal(spec.slippage_bps)
    last_target: Decimal | None = None
    trades: list[dict[str, str]] = []
    equity: list[dict[str, str]] = []
    for index, bar in enumerate(bars[:-1]):
        at = datetime.fromtimestamp(bar.timestamp / 1000, UTC)
        if (index >= spec.warmup_bars and at.minute == 0 and at.second == 0
                and at.microsecond == 0 and at.hour % spec.decision_interval_hours == 0):
            days, phase = _phase(at, spec)
            target = Decimal("0") if phase == "bear_onset" else Decimal("1")
            if last_target is None:
                last_target = target
            elif target != last_target:
                next_bar = bars[index + 1]
                next_at = datetime.fromtimestamp(next_bar.timestamp / 1000, UTC)
                direction = Decimal("1") if target > last_target else Decimal("-1")
                fill_price = next_bar.open * (Decimal("1") + direction * bps / Decimal("10000"))
                total = cash + btc * next_bar.open
                requested = total * target / next_bar.open
                affordable = cash / (fill_price * (Decimal("1") + fee_rate))
                target_btc = min(requested, btc + affordable).quantize(QTY, rounding=ROUND_DOWN)
                delta = target_btc - btc
                qty = abs(delta)
                fee = (qty * fill_price * fee_rate).quantize(QTY)
                cash_before, btc_before = cash, btc
                if delta > 0:
                    cash -= qty * fill_price + fee
                else:
                    cash += qty * fill_price - fee
                btc += delta
                trades.append({
                    "sequence": str(len(trades) + 1), "decision_timestamp": at.isoformat(),
                    "information_cutoff": at.isoformat(), "phase": phase,
                    "days_since_halving": str(days), "previous_target": str(last_target),
                    "new_target": str(target), "side": "buy" if delta > 0 else "sell",
                    "fill_timestamp": next_at.isoformat(), "fill_open": str(next_bar.open),
                    "fill_high": str(next_bar.high), "fill_low": str(next_bar.low),
                    "fill_close": str(next_bar.close), "quantity": str(qty),
                    "fill_price": str(fill_price), "fee": str(fee),
                    "cash_before": str(cash_before), "cash_after": str(cash),
                    "btc_before": str(btc_before), "btc_after": str(btc),
                    "equity_after": str(cash + btc * next_bar.close),
                })
                last_target = target
        if index >= spec.warmup_bars:
            equity.append({"timestamp": at.isoformat(), "cash": str(cash), "btc": str(btc),
                           "close": str(bar.close), "equity": str(cash + btc * bar.close)})
    last = bars[-1]
    equity.append({"timestamp": datetime.fromtimestamp(last.timestamp / 1000, UTC).isoformat(),
                   "cash": str(cash), "btc": str(btc), "close": str(last.close),
                   "equity": str(cash + btc * last.close)})
    return trades, equity


def export_package(cache: Path, out: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    start, end = datetime(2014, 4, 26, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)
    bars, spec = load_canonical(cache, start, end), Spec()
    trades, equity = run(bars, spec)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "candles.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_ms", "open", "high", "low", "close", "volume"])
        writer.writerows([[bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in bars])
    for name, rows in (("expected_orders.csv", trades), ("certified_trades.csv", trades), ("equity_curve.csv", equity)):
        with (out / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    phases = [{"decision_timestamp": row["decision_timestamp"], "phase": row["phase"], "target": row["new_target"]} for row in trades]
    (out / "expected_phase_transitions.csv").write_text("decision_timestamp,phase,target\n" + "\n".join(
        f"{row['decision_timestamp']},{row['phase']},{row['target']}" for row in phases) + "\n", encoding="utf-8")
    (out / "strategy_spec.json").write_text(json.dumps(asdict(spec), indent=2), encoding="utf-8")
    digest = hashlib.sha256(cache.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps({"canonical_cache_sha256": digest, "rows": len(bars),
        "final_equity": equity[-1]["equity"], "trades": len(trades), "spec": "strategy_spec.json"}, indent=2), encoding="utf-8")
    (out / "README.md").write_text("# V7 independent replication\n\nUse `candles.csv`, `strategy_spec.json`, completed-bar decisions and next-open fills. No MatiTradingBot import is required.\n", encoding="utf-8")
    return trades, equity
