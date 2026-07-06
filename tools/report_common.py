"""
Runner compartido para las herramientas de reporte/auditoria (visor generico y
auditor exhaustivo). Conduce el MISMO path de backtest que el CLI (`cli.runner`)
—carga de macro/market/funding, registry, BacktestEngine— pero devuelve el objeto
estrategia y las barras, que el CLI no expone. Asi el reporte es agnostico a la
estrategia: los marcadores salen de la estrategia (`_rebalance_log` para allocators,
`_journal` para estrategias de trades) y la equity de `result.equity_curve`.

No re-implementa el motor: reusa `core.backtest` y `strategies.registry`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.registry import get as get_strategy


@dataclass(frozen=True)
class RunOutput:
    result: Any                 # BacktestResult
    strategy: Any               # instancia del bot tras la simulacion
    bars: list[Any]             # OHLCVBar incluyendo warmup
    symbol: str
    from_dt: datetime
    to_dt: datetime
    cost_mode: str
    config: dict[str, Any]


def cache_bounds(symbol: str, timeframe: str = "1H") -> tuple[datetime, datetime] | None:
    """Rango [min, max] UTC cubierto por el cache OHLCV en disco, o None si no existe.

    Sirve para CLAMPAR peticiones y no disparar re-descarga/merge que mutaria el
    dataset canonico (regla 4 de determinismo). El cache canonico NO debe crecer
    por una herramienta de reporte.
    """
    from data import ohlcv_cache
    meta = ohlcv_cache.load_meta(symbol, timeframe)
    bars = (meta or {}).get("bars") if meta else None
    if not bars:
        return None
    lo = datetime.fromtimestamp(int(bars[0][0]) / 1000, tz=timezone.utc)
    hi = datetime.fromtimestamp(int(bars[-1][0]) / 1000, tz=timezone.utc)
    return lo, hi


def parse_utc(raw: str) -> datetime:
    """YYYY-MM-DD (o ISO) -> datetime UTC. Acepta solo el anio como atajo."""
    if len(raw) == 4 and raw.isdigit():
        raw = f"{raw}-01-01"
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


def run_strategy(
    *,
    symbol: str,
    strategy: str,
    from_dt: datetime,
    to_dt: datetime,
    cost_mode: str = "realistic",
    config: dict[str, Any] | None = None,
    timeframe: str = "1H",
    balance: float = 10000.0,
    bars: list[Any] | None = None,
    quiet: bool = True,
) -> RunOutput:
    """Ejecuta un backtest y devuelve result + estrategia + barras."""
    config = config or {}
    meta = get_strategy(strategy)
    warmup_start = from_dt - timedelta(days=meta.warmup_days)

    # Contexto externo (idempotente/cacheado); silenciar loguru si quiet.
    if quiet:
        from loguru import logger
        logger.remove()
    from strategies.macro_context import load_macro_context
    from strategies.market_context import load_market_context
    from strategies.funding_context import load_funding_history

    load_macro_context(from_dt, to_dt, symbol)
    load_market_context(from_dt, to_dt)
    load_funding_history(symbol, from_dt, to_dt)

    if bars is None:
        bars = fetch_historical_bars(symbol=symbol, bar=timeframe,
                                     from_dt=warmup_start, to_dt=to_dt)
    if not bars:
        raise RuntimeError(f"sin barras para {symbol} {from_dt.date()}..{to_dt.date()}")

    from_ts = int(from_dt.timestamp() * 1000)
    warmup_bars = max(len([b for b in bars if b.timestamp < from_ts]), 20)

    client = BacktestClient(symbol=symbol, bars=bars,
                            initial_balance=Decimal(str(balance)), cost_mode=cost_mode)

    def factory(c, s):
        cfg_obj = meta.make_config(symbol.upper(), config)
        return meta.make_bot(c, cfg_obj, s)

    engine = BacktestEngine(bt_client=client, strategy_factory=factory,
                            warmup_bars=warmup_bars, timeframe=timeframe)
    result = engine.run()
    return RunOutput(result=result, strategy=engine.last_strategy, bars=bars,
                     symbol=symbol, from_dt=from_dt, to_dt=to_dt,
                     cost_mode=cost_mode, config=config)


# ---------------------------------------------------------------------------
# Extraccion de series y marcadores (agnostica a la estrategia)
# ---------------------------------------------------------------------------

def daily_candles(bars: list[Any], from_dt: datetime, to_dt: datetime
                  ) -> list[tuple[str, float, float, float, float]]:
    """1H -> velas diarias UTC dentro de [from, to]: (fecha, o, h, l, c)."""
    f_ms = int(from_dt.timestamp() * 1000)
    t_ms = int(to_dt.replace(hour=23, minute=59).timestamp() * 1000)
    days: dict[str, list] = {}
    for b in bars:
        ts = int(b.timestamp)
        if ts < f_ms or ts > t_ms:
            continue
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        o, h, l, c = float(b.open), float(b.high), float(b.low), float(b.close)
        if d not in days:
            days[d] = [o, h, l, c]
        else:
            row = days[d]
            row[1] = max(row[1], h)
            row[2] = min(row[2], l)
            row[3] = c
    return [(d, *days[d]) for d in sorted(days)]


def equity_series(result: Any, candles: list) -> dict[str, list]:
    """Series diarias alineadas: dates, equity, bnh, dd (%). B&H con coste de entrada (F11)."""
    from bisect import bisect_right
    curve = result.equity_curve or []
    if not curve:
        return {"dates": [], "equity": [], "bnh": [], "dd": []}

    ev_ts = [int(dt.timestamp() * 1000) for dt, _ in curve]
    ev_val = [float(v) for _, v in curve]

    # coste de entrada B&H aproximado con el modo (fee 0.1% + slippage del modo)
    slip = {"ideal": 0.0, "realistic": 0.0005, "conservative": 0.0015,
            "bybit": 0.0002, "bybit_cons": 0.0010}.get(result.cost_mode, 0.0005)
    fee = 0.00055 if str(result.cost_mode).startswith("bybit") else 0.001
    initial = float(result.initial_balance)
    p0 = candles[0][4] if candles else 0.0
    bnh_qty = initial / (p0 * (1 + slip) * (1 + fee)) if p0 > 0 else 0.0

    dates, equity, bnh = [], [], []
    for d, _o, _h, _l, c in candles:
        day_end = int(datetime.strptime(d, "%Y-%m-%d")
                      .replace(hour=23, minute=59, tzinfo=timezone.utc).timestamp() * 1000)
        i = bisect_right(ev_ts, day_end) - 1
        eq = ev_val[i] if i >= 0 else initial
        dates.append(d)
        equity.append(round(eq, 2))
        bnh.append(round(bnh_qty * c, 2))

    peak, dd = equity[0], []
    for eq in equity:
        peak = max(peak, eq)
        dd.append(round((eq - peak) / peak * 100, 2) if peak > 0 else 0.0)
    return {"dates": dates, "equity": equity, "bnh": bnh, "dd": dd}


def extract_markers(strategy: Any) -> tuple[list[dict], str]:
    """
    Marcadores normalizados agnosticos al formato:
      {date, ts, kind: entry|exit|init, side, price, pnl, info}
    Devuelve (markers, output_kind) con output_kind in {allocator, trade, none}.
    """
    reb = getattr(strategy, "_rebalance_log", None)
    if reb:
        out = []
        for r in reb:
            d = str(r.get("timestamp", ""))[:10]
            direction = r.get("direction", "")
            kind = "init" if direction == "INIT" else ("entry" if direction == "BUY" else "exit")
            out.append({
                "date": d, "ts": str(r.get("timestamp", ""))[:16].replace("T", " "),
                "kind": kind, "side": direction, "price": float(r.get("price", 0.0)),
                "pnl": None,
                "info": (f"{round(float(r.get('btc_pct_before', 0))*100)}% -> "
                         f"{round(float(r.get('btc_pct_after', 0))*100)}% "
                         f"(target {round(float(r.get('btc_pct_target', 0))*100)}%) | "
                         + ", ".join(r.get("signals", []))),
            })
        return out, "allocator"

    journal = getattr(strategy, "_journal", None)
    if journal:
        out = []
        for t in journal:
            op = t.get("open", {})
            side = t.get("side", "long")
            if op.get("price"):
                out.append({
                    "date": str(op.get("timestamp", ""))[:10],
                    "ts": str(op.get("timestamp", ""))[:16].replace("T", " "),
                    "kind": "entry", "side": side, "price": float(op.get("price", 0.0)),
                    "pnl": None, "info": f"ENTRY {side} | {op.get('reason', '')}",
                })
            cl = t.get("close", {})
            if cl.get("price"):
                pnl = cl.get("true_pnl_usdt", cl.get("pnl_usdt"))
                out.append({
                    "date": str(cl.get("timestamp", ""))[:10],
                    "ts": str(cl.get("timestamp", ""))[:16].replace("T", " "),
                    "kind": "exit", "side": side, "price": float(cl.get("price", 0.0)),
                    "pnl": (float(pnl) if pnl is not None else None),
                    "info": f"EXIT {side} | {cl.get('reason', '')}",
                })
        return out, "trade"

    return [], "none"
