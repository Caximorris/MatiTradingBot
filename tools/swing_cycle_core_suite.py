"""Manifest-backed, resumable research suite for the isolated v7 Cycle Core.

The suite reads the canonical cache directly and never downloads, rewrites, or
deduplicates it.  It intentionally does not reuse ``btc_cycle_resumable.py``:
that tool's checkpoint identity is not the candle identity it executes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "backtests" / "v7_cycle_core"
CACHE = ROOT / "data" / "cache" / "BTC-USDT_1H.json"
FUNDING = ROOT / "data" / "cache" / "funding_bybit_BTCUSDT.json"
START = datetime(2015, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    for attempt in range(5):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.25 * (attempt + 1))


def load_bars() -> tuple[list[Any], dict[str, Any]]:
    from data.market_data import OHLCVBar

    raw = json.loads(CACHE.read_text(encoding="utf-8"))
    rows = raw["bars"]
    bars = [OHLCVBar(int(r[0]), Decimal(r[1]), Decimal(r[2]), Decimal(r[3]),
                     Decimal(r[4]), Decimal(r[5])) for r in rows]
    timestamps = [bar.timestamp for bar in bars]
    unique = len(set(timestamps))
    from_ms, to_ms = int(START.timestamp() * 1000), int(END.timestamp() * 1000)
    sliced = [bar for bar in bars if from_ms <= bar.timestamp <= to_ms]
    warmup_ms = int((START - timedelta(days=250)).timestamp() * 1000)
    effective = [bar for bar in bars if warmup_ms <= bar.timestamp <= to_ms]
    return effective, {
        "cache_path": str(CACHE.relative_to(ROOT)), "raw_sha256": _sha(CACHE),
        "semantic_sha256": hashlib.sha256(_json(rows).encode()).hexdigest(),
        "raw_rows": len(rows), "distinct_timestamps": unique,
        "duplicate_rows": len(rows) - unique, "slice_rows_inclusive": len(sliced),
        "effective_rows_with_warmup": len(effective),
        "slice_start_utc": START.isoformat(), "slice_end_utc": END.isoformat(),
        "slice_semantics": "inclusive from_ms <= timestamp <= to_ms",
    }


def _clock_dates(shift: int = 0) -> list[str]:
    base = (date(2012, 11, 28), date(2016, 7, 9), date(2020, 5, 11), date(2024, 4, 20))
    return [(item + timedelta(days=shift)).isoformat() for item in base]


def specs() -> list[dict[str, Any]]:
    # The local Bybit snapshot is explicitly fail-closed and cannot certify v6-2.
    # This frozen-code, overlay-disabled control is the strongest reproducible
    # current-input replacement; the failed overlay-on cases stay in the index.
    v6 = {"use_phase_policy_router": True, "phase_policy_profile": "v5_equiv",
          "use_funding_overlay": False, "funding_overlay_source": "bybit"}
    rows = [
        {"id": "A_buy_hold", "strategy": "swing_cycle_core", "config": {"bear_onset_btc_pct": "1"}, "cost": "realistic"},
        {"id": "B_v6_reproducible_current_inputs", "strategy": "swing_allocator", "config": v6, "cost": "realistic"},
        {"id": "B_v6_shared_cadence_current_inputs", "strategy": "swing_allocator", "config": v6 | {"clock_aligned_cadence": True}, "cost": "realistic"},
        {"id": "C_v6_no_ema50_cap", "strategy": "swing_allocator", "config": v6 | {"bull_peak_ema50_cap_enabled": False}, "cost": "realistic"},
        {"id": "D_bull_phase_hold", "strategy": "swing_allocator", "config": v6 | {"phase_policy_profile": "bull_phase_hold_research"}, "cost": "realistic"},
        {"id": "E_v7_cycle_core", "strategy": "swing_cycle_core", "config": {"bear_onset_btc_pct": "0"}, "cost": "realistic"},
        {"id": "F_v7_conservative_bear", "strategy": "swing_cycle_core", "config": {"bear_onset_btc_pct": "0.2"}, "cost": "realistic"},
    ]
    for bear in (480, 540, 600):
        for accum in (840, 900, 960):
            rows.append({"id": f"sensitivity_b{bear}_a{accum}", "strategy": "swing_cycle_core",
                         "config": {"bear_onset_btc_pct": "0", "phase_bear_start": bear,
                                    "phase_accumulation_start": accum}, "cost": "realistic"})
    for label, cfg in (("shift_minus_120", {"phase_bear_start": 420, "phase_accumulation_start": 780}),
                       ("shift_plus_120", {"phase_bear_start": 660, "phase_accumulation_start": 1020}),
                       ("bear_plus_180", {"phase_bear_start": 540, "phase_accumulation_start": 1080}),
                       ("bear_minus_180", {"phase_bear_start": 540, "phase_accumulation_start": 720})):
        rows.append({"id": f"stress_{label}", "strategy": "swing_cycle_core", "config": {"bear_onset_btc_pct": "0"} | cfg, "cost": "realistic"})
    for label, cost in (("realistic", "realistic"), ("conservative", "conservative"), ("twice_conservative", "twice_conservative")):
        rows.append({"id": f"cost_{label}", "strategy": "swing_cycle_core", "config": {"bear_onset_btc_pct": "0"}, "cost": cost})
    for delay in (1, 6, 12, 24, 72):
        rows.append({"id": f"delay_{delay}h", "strategy": "swing_cycle_core", "config": {"bear_onset_btc_pct": "0", "transition_delay_hours": delay}, "cost": "realistic"})
    for shift in (-365, -180, 0, 180, 365):
        rows.append({"id": f"placebo_{shift:+d}d", "strategy": "swing_cycle_core", "config": {"bear_onset_btc_pct": "0", "confirmed_halving_dates": _clock_dates(shift)}, "cost": "realistic"})
    return rows


def _run(spec: dict[str, Any], bars: list[Any], dataset: dict[str, Any]) -> dict[str, Any]:
    from core.backtest import BacktestClient, BacktestEngine
    from reporting.experiment_manifest import write_experiment_manifest
    from strategies.registry import get

    started = time.perf_counter()
    meta = get(spec["strategy"])
    config = dict(spec["config"])
    cfg = meta.make_config("BTC-USDT", config)
    client_kwargs: dict[str, Any] = {"symbol": "BTC-USDT", "bars": bars,
                                     "initial_balance": Decimal("10000"), "cost_mode": spec["cost"]}
    if spec["cost"] == "twice_conservative":
        client_kwargs.update(cost_mode="twice_conservative", fee_rate=Decimal("0.002"), slippage_bps=30)
    client = BacktestClient(**client_kwargs)
    warmup = sum(bar.timestamp < int(START.timestamp() * 1000) for bar in bars)
    engine = BacktestEngine(client, lambda c, s: meta.make_bot(c, cfg, s), warmup_bars=max(20, warmup), timeframe="1H")
    result = engine.run()
    strategy = engine.last_strategy
    manifest = write_experiment_manifest(
        result=result, requested_strategy=spec["strategy"], resolved_strategy=meta.name,
        config_overrides=config, resolved_config=cfg.to_dict(), symbol="BTC-USDT", timeframe="1H",
        requested_from=START, requested_to=END, warmup_bars=max(20, warmup), initial_balance=Decimal("10000"),
        cost_mode=spec["cost"], fee_rate=client._fee_rate, slippage_bps=client._slippage_bps,
        fill_next_open=client.fill_next_open, bars=bars,
        external_inputs=[FUNDING] if spec["strategy"] == "swing_allocator" else (),
    )
    executed = list(client._executed)
    fees = sum((trade.fee for trade in executed), Decimal("0"))
    turnover = sum((trade.quantity * trade.price for trade in executed), Decimal("0"))
    return {
        "status": "SUCCEEDED", "id": spec["id"], "strategy": meta.name, "config": cfg.to_dict(),
        "cost": spec["cost"], "started_at": _now(), "runtime_seconds": round(time.perf_counter() - started, 3),
        "manifest": str(Path(manifest)), "dataset": dataset,
        "final_capital": str(result.final_balance), "total_return_pct": str(result.total_pnl_pct),
        "cagr": str(result.cagr), "max_drawdown_pct": str(result.max_drawdown_pct),
        "calmar": str(result.calmar), "sharpe": str(result.sharpe_ratio), "sortino": str(result.sortino),
        "underwater_days": result.underwater_days, "orders": len(executed), "fills": len(executed),
        "trades": result.total_trades, "fees": str(fees), "turnover": str(turnover),
        # Daily marks preserve phase/cycle attribution while keeping a resumable
        # index compact; the authoritative full curve remains hashed in its manifest.
        "buy_hold_return_pct": str(result.buy_hold_pnl_pct),
        "equity_curve": [(ts.isoformat(), str(v)) for ts, v in result.equity_curve if ts.hour == 0],
        "transitions": getattr(strategy, "_transition_log", []), "decisions": getattr(strategy, "_decision_log", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    index_path = args.out / "index.json"
    state = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"cases": {}}
    bars, dataset = load_bars()
    suite = specs()
    suite_sha = hashlib.sha256(_json({"dataset": dataset, "cases": suite,
        "strategy_sha256": _sha(ROOT / "strategies" / "swing_cycle_core.py"),
        "clock_sha256": _sha(ROOT / "strategies" / "cycle_phase_clock.py")}).encode()).hexdigest()
    if state.get("suite_sha256") != suite_sha:
        state = {"suite_sha256": suite_sha, "cases": {}}
    _atomic(args.out / "suite_spec.json", {"generated_at": _now(), "dataset": dataset, "cases": suite})
    for spec in suite:
        old = state["cases"].get(spec["id"], {})
        if not args.force and old.get("status") == "SUCCEEDED" and old.get("suite_sha256") == suite_sha and Path(old.get("manifest", "")).exists():
            continue
        try:
            state["cases"][spec["id"]] = _run(spec, bars, dataset) | {"suite_sha256": suite_sha}
        except Exception as exc:
            state["cases"][spec["id"]] = {"status": "FAILED", "id": spec["id"], "error": f"{type(exc).__name__}: {exc}", "dataset": dataset}
        _atomic(index_path, state)
        print(f"{spec['id']},{state['cases'][spec['id']]['status']}", flush=True)
    complete = all(state["cases"].get(spec["id"], {}).get("status") == "SUCCEEDED" for spec in suite)
    _atomic(args.out / "completeness.json", {"complete": complete, "expected_cases": len(suite), "completed_cases": sum(x.get("status") == "SUCCEEDED" for x in state["cases"].values()), "dataset_unchanged": _sha(CACHE) == dataset["raw_sha256"]})
    if not complete:
        raise SystemExit("suite incomplete; inspect index.json and rerun")


if __name__ == "__main__":
    main()
