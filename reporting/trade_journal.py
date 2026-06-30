"""
Trade Journal — registro exhaustivo de cada operación con todos los indicadores,
scores y contexto disponibles en el momento de apertura y cierre.

Escrito automáticamente al finalizar cada backtest en el directorio `backtests/`.
El archivo JSON resultante es la base para el análisis y mejora de estrategias.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal


def _serialize(obj):
    """Convierte cualquier valor a tipo JSON-serializable de forma recursiva."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    if isinstance(obj, (bool, int, float, str)) or obj is None:
        return obj
    return str(obj)


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_true_pnl(trade: dict) -> float:
    """PnL real del trade completo, incluyendo partial exits si el balance esta disponible."""
    close = trade.get("close", {})
    open_ = trade.get("open", {})

    before = open_.get("balance_usdt_before")
    after = close.get("balance_usdt_after")
    if before is not None and after is not None:
        return _as_float(after) - _as_float(before)

    return _as_float(close.get("pnl_usdt"))


def _augment_true_pnl(trade: dict) -> None:
    """Anade campos de PnL real sin eliminar el PnL del cierre final."""
    if "close" not in trade:
        return

    close = trade["close"]
    true_pnl = _trade_true_pnl(trade)
    close_pnl = _as_float(close.get("pnl_usdt"))
    close["true_pnl_usdt"] = round(true_pnl, 2)
    close["close_pnl_usdt"] = round(close_pnl, 2)
    close["balance_pnl_adjustment_usdt"] = round(true_pnl - close_pnl, 2)

    invest = _as_float(trade.get("open", {}).get("invest_usdt"))
    if invest:
        true_pnl_pct = true_pnl / invest * 100
        close["true_pnl_pct"] = round(true_pnl_pct, 2)

        mfe_pct = _as_float(close.get("mfe_pct"))
        close["giveback_pct"] = round(mfe_pct - true_pnl_pct, 2)

    open_price = _as_float(trade.get("open", {}).get("price"))
    close_price = _as_float(close.get("price"))
    if open_price > 0 and close_price > 0:
        close_price_return_pct = (close_price / open_price - 1) * 100
        close["close_price_return_pct"] = round(close_price_return_pct, 2)
        close["exit_from_peak_pct"] = round(_as_float(close.get("mfe_pct")) - close_price_return_pct, 2)

    indicators = close.get("indicators", {})
    if isinstance(indicators, dict):
        close["partial_exit_triggered"] = bool(indicators.get("partial_exit_triggered", False))


def _compute_stats(trades: list[dict]) -> dict:
    """Estadísticas agregadas del journal completo."""
    closed = [t for t in trades if "close" in t]
    if not closed:
        return {}

    pnls       = [_as_float(t["close"].get("true_pnl_usdt", t["close"].get("pnl_usdt", 0))) for t in closed]
    close_pnls = [_as_float(t["close"].get("pnl_usdt", 0)) for t in closed]
    pnl_pcts   = [_as_float(t["close"].get("true_pnl_pct", t["close"].get("pnl_pct", 0))) for t in closed]
    hold_hrs  = [t["close"]["holding_hours"]   for t in closed if "holding_hours"  in t["close"]]
    maes      = [t["close"]["mae_pct"]         for t in closed if "mae_pct"         in t["close"]]
    mfes      = [t["close"]["mfe_pct"]         for t in closed if "mfe_pct"         in t["close"]]
    rs        = [t["close"]["r_multiple"]      for t in closed if "r_multiple"      in t["close"]]

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    by_reason:  dict[str, int] = {}
    by_side:    dict[str, int] = {}
    win_by_reason: dict[str, int] = {}
    loss_by_reason: dict[str, int] = {}

    for t in closed:
        r = t["close"].get("reason", "unknown")
        s = t.get("side", "unknown")
        by_reason[r]  = by_reason.get(r, 0)  + 1
        by_side[s]    = by_side.get(s, 0)    + 1
        p = _as_float(t["close"].get("true_pnl_usdt", t["close"].get("pnl_usdt", 0)))
        if p > 0:
            win_by_reason[r]  = win_by_reason.get(r, 0)  + 1
        else:
            loss_by_reason[r] = loss_by_reason.get(r, 0) + 1

    # Win rate por razón de salida (útil para entender qué exits funcionan)
    wr_by_reason = {}
    for r, total in by_reason.items():
        wins_r = win_by_reason.get(r, 0)
        wr_by_reason[r] = round(wins_r / total * 100, 1) if total else 0

    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    pf = round(gross_win / gross_loss, 3) if gross_loss > 0 else 0
    close_pnl_total = sum(close_pnls)
    true_pnl_total = sum(pnls)
    pnl_adjustment = true_pnl_total - close_pnl_total

    return {
        "total_trades":          len(closed),
        "winners":               len(wins),
        "losers":                len(losses),
        "win_rate_pct":          round(len(wins) / len(closed) * 100, 2),
        "total_pnl_usdt":        round(true_pnl_total, 2),
        "total_close_pnl_usdt":  round(close_pnl_total, 2),
        "balance_pnl_adjustment_usdt": round(pnl_adjustment, 2),
        "uses_balance_pnl":      any(abs(p - c) > 0.01 for p, c in zip(pnls, close_pnls)),
        "avg_pnl_usdt":          round(sum(pnls) / len(pnls), 2) if pnls else 0,
        "median_pnl_usdt":       round(sorted(pnls)[len(pnls) // 2], 2) if pnls else 0,
        "avg_pnl_pct":           round(sum(pnl_pcts) / len(pnl_pcts), 2) if pnl_pcts else 0,
        "best_trade_usdt":       round(max(pnls), 2) if pnls else 0,
        "worst_trade_usdt":      round(min(pnls), 2) if pnls else 0,
        "avg_winner_usdt":       round(gross_win / len(wins), 2) if wins else 0,
        "avg_loser_usdt":        round(sum(losses) / len(losses), 2) if losses else 0,
        "largest_win_pct":       round(max(pnl_pcts), 2) if pnl_pcts else 0,
        "largest_loss_pct":      round(min(pnl_pcts), 2) if pnl_pcts else 0,
        "profit_factor":         pf,
        "avg_holding_hours":     round(sum(hold_hrs) / len(hold_hrs), 1) if hold_hrs else 0,
        "min_holding_hours":     round(min(hold_hrs), 1) if hold_hrs else 0,
        "max_holding_hours":     round(max(hold_hrs), 1) if hold_hrs else 0,
        "by_side":               by_side,
        "by_exit_reason":        by_reason,
        "win_rate_by_reason":    wr_by_reason,
        "avg_mae_pct":           round(sum(maes) / len(maes), 2) if maes else 0,
        "avg_mfe_pct":           round(sum(mfes) / len(mfes), 2) if mfes else 0,
        "max_mae_pct":           round(max(maes), 2) if maes else 0,
        "max_mfe_pct":           round(max(mfes), 2) if mfes else 0,
        "avg_r_multiple":        round(sum(rs) / len(rs), 2) if rs else 0,
        "r_multiples":           [round(r, 2) for r in rs],
    }


def write_journal(
    journal: list[dict],
    strategy_name: str,
    symbol: str,
    timeframe: str,
    from_date: str,
    to_date: str,
    output_dir: str = "backtests",
    cost_mode: str = "ideal",
    config_overrides: dict | None = None,
    resolved_config: dict | None = None,
    backtest_summary: dict | None = None,
) -> str:
    """
    Escribe el journal completo a un archivo JSON.
    Devuelve la ruta del archivo generado.
    """
    os.makedirs(output_dir, exist_ok=True)

    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sym = symbol.replace("-", "")
    fn  = f"journal_{strategy_name}_{sym}_{timeframe}_{ts}.json"
    fp  = os.path.join(output_dir, fn)

    for trade in journal:
        _augment_true_pnl(trade)

    closed = [t for t in journal if "close" in t]

    output = {
        "meta": {
            "strategy":            strategy_name,
            "symbol":              symbol,
            "timeframe":           timeframe,
            "period":              f"{from_date} -> {to_date}",
            "generated_at":        datetime.now(timezone.utc).isoformat(),
            "cost_mode":           cost_mode,
            "config_overrides":    config_overrides or {},
            "resolved_config":     _serialize(resolved_config or {}),
            "backtest":            _serialize(backtest_summary or {}),
            "total_closed_trades": len(closed),
            "open_at_end":         len(journal) - len(closed),
        },
        "statistics": _compute_stats(closed),
        "trades":     [_serialize(t) for t in journal],
    }

    with open(fp, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return fp
