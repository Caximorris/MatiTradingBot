"""
Journal de rebalanceos para BTC Swing Allocator.
Registra cada evento de ajuste de allocation con su contexto.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def write_swing_journal(
    rebalance_log: list[dict],
    strategy_name: str,
    symbol: str,
    timeframe: str,
    from_date: str,
    to_date: str,
    cost_mode: str,
    config_overrides: dict,
    initial_balance: float,
    final_balance: float,
    final_btc_qty: float = 0.0,
    resolved_config: dict | None = None,
    backtest_summary: dict | None = None,
) -> str:
    """
    Escribe el journal de rebalanceos en backtests/journal_{strategy}_{symbol}_{tf}_{ts}.json.
    Retorna la ruta del archivo creado.
    """
    ts  = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    sym = symbol.replace("-", "").upper()
    strat_slug = strategy_name.lower().replace("-", "_").replace(" ", "_")
    fname = f"journal_{strat_slug}_{sym}_{timeframe}_{ts}.json"
    out   = Path("backtests") / fname
    out.parent.mkdir(parents=True, exist_ok=True)

    # Estadisticas resumidas
    rebalances = [r for r in rebalance_log if r["direction"] != "INIT"]
    buys  = [r for r in rebalances if r["direction"] == "BUY"]
    sells = [r for r in rebalances if r["direction"] == "SELL"]

    pcts = [r["btc_pct_after"] for r in rebalance_log]
    avg_btc_pct = round(sum(pcts) / len(pcts) * 100, 1) if pcts else 0.0

    # BTC acumulado vs Buy & Hold
    init_event = next((r for r in rebalance_log if r["direction"] == "INIT"), None)
    init_price = init_event["price"] if init_event else 0.0
    bnh_btc    = round(initial_balance / init_price, 6) if init_price > 0 else 0.0
    btc_ratio  = round(final_btc_qty / bnh_btc, 4) if bnh_btc > 0 else 0.0

    # Signals frecuencia
    all_signals: list[str] = []
    for r in rebalances:
        all_signals.extend(r.get("signals", []))
    signal_freq: dict[str, int] = {}
    for s in all_signals:
        base_s = s.split("_")[0] + ("_" + s.split("_")[1] if s.count("_") >= 1 else "")
        signal_freq[base_s] = signal_freq.get(base_s, 0) + 1

    stats = {
        "total_rebalances":      len(rebalances),
        "buy_count":             len(buys),
        "sell_count":            len(sells),
        "avg_btc_pct":           avg_btc_pct,
        "min_btc_pct":           round(min(pcts) * 100, 1) if pcts else 0.0,
        "max_btc_pct":           round(max(pcts) * 100, 1) if pcts else 0.0,
        "initial_balance_usdt":  round(initial_balance, 2),
        "final_balance_usdt":    round(final_balance, 2),
        "pnl_pct":               round((final_balance / initial_balance - 1) * 100, 2)
                                 if initial_balance > 0 else 0.0,
        "final_btc_qty":         round(final_btc_qty, 6),
        "bnh_initial_btc":       bnh_btc,
        "btc_vs_bnh_ratio":      btc_ratio,
        "signal_frequency":      signal_freq,
    }

    doc = {
        "meta": {
            "strategy":        strategy_name,
            "symbol":          symbol,
            "timeframe":       timeframe,
            "from_date":       from_date,
            "to_date":         to_date,
            "cost_mode":       cost_mode,
            "config_overrides": config_overrides,
            "resolved_config": resolved_config or {},
            "backtest":        backtest_summary or {},
            "generated_at":    datetime.now(tz=timezone.utc).isoformat(),
        },
        "statistics": stats,
        "rebalances":  rebalance_log,
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, default=str)

    return str(out)
