#!/usr/bin/env python
"""Distribucion MENSUAL de retornos de un backtest, desde su journal (plan income M0).

Responde la pregunta que CAGR/MaxDD no responden: "esto se parece a una nomina o no".
Media/mediana mensual, % meses positivos, peor/mejor mes, racha maxima de meses negativos.

Metodo: serie de equity = balance de caja tras cada cierre (`close.balance_usdt_after`),
carry-forward a fin de mes. El PnL por trade NO incluye el funding devengado via
adjust_balance; el balance de caja SI — por eso se usa el balance y no la suma de PnLs.

LIMITACION: solo es correcto para estrategias FLAT entre trades (funding_extreme,
mr_regime, scalp...). Un journal de rebalanceos (swing) mantiene BTC en cartera y el
balance de caja no es el equity -> se rechaza con error.

Usage:
    python tools/monthly_dist.py backtests/journal_funding_extreme_..._20260713.json
    python tools/monthly_dist.py --latest funding
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timezone

BACKTESTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests")


def _resolve_latest(token: str) -> str | None:
    pattern = os.path.join(BACKTESTS_DIR, f"journal_*{token}*.json")
    matches = glob.glob(pattern)
    return max(matches, key=os.path.getmtime) if matches else None


def _month_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m")


def _parse_ts(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def monthly_returns(closes: list[tuple[datetime, float]], initial_balance: float,
                    start: datetime, end: datetime) -> list[tuple[str, float]]:
    """[(\"YYYY-MM\", ret)] con equity carry-forward a fin de mes.

    `closes` = [(ts_cierre, balance_despues)] ordenados; meses sin cierres repiten
    el ultimo balance (ret 0.0).
    """
    if end < start:
        return []
    closes = sorted(closes)
    out: list[tuple[str, float]] = []
    equity_prev = initial_balance
    idx = 0
    equity = initial_balance
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        # avanzar hasta el ultimo cierre dentro de este mes
        while idx < len(closes) and (closes[idx][0].year, closes[idx][0].month) <= (year, month):
            equity = closes[idx][1]
            idx += 1
        key = f"{year:04d}-{month:02d}"
        out.append((key, equity / equity_prev - 1.0 if equity_prev else 0.0))
        equity_prev = equity
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def summarize(rets: list[tuple[str, float]]) -> dict:
    vals = [r for _, r in rets]
    n = len(vals)
    if not n:
        return {}
    pos = [v for v in vals if v > 0]
    srt = sorted(vals)
    median = (srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2)
    worst_streak = streak = 0
    for v in vals:
        streak = streak + 1 if v < 0 else 0
        worst_streak = max(worst_streak, streak)
    return {
        "months": n,
        "mean": sum(vals) / n,
        "median": median,
        "pct_positive": len(pos) / n,
        "best": max(vals),
        "worst": min(vals),
        "max_neg_streak": worst_streak,
    }


def main(argv: list[str]) -> int:
    if "--latest" in argv:
        i = argv.index("--latest")
        token = argv[i + 1] if i + 1 < len(argv) else ""
        path = _resolve_latest(token)
        if not path:
            print(f"No journal matching '{token}' in {BACKTESTS_DIR}", file=sys.stderr)
            return 1
    elif argv:
        path = argv[0]
    else:
        print(__doc__)
        return 1

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    trades = data.get("trades")
    if not trades:
        print("Journal sin 'trades' (es de rebalanceos?). Esta herramienta solo vale "
              "para estrategias flat entre trades — ver docstring.", file=sys.stderr)
        return 1

    closes = [(_parse_ts(t["close"]["timestamp"]), float(t["close"]["balance_usdt_after"]))
              for t in trades if t.get("close", {}).get("balance_usdt_after") is not None]
    if not closes:
        print("Ningun trade cerrado con balance_usdt_after en el journal.", file=sys.stderr)
        return 1

    initial = float(trades[0]["open"].get("balance_usdt_before", 0.0))
    start = _parse_ts(trades[0]["open"]["timestamp"])
    end = max(ts for ts, _ in closes)

    rets = monthly_returns(closes, initial, start, end)
    s = summarize(rets)

    print(f"# {os.path.basename(path)}")
    print(f"Meses: {s['months']}  (de {rets[0][0]} a {rets[-1][0]}; balance inicial {initial:,.0f})")
    print()
    # grid por ano: 12 columnas
    years = sorted({k[:4] for k, _ in rets})
    by_key = dict(rets)
    header = "Ano   " + "".join(f"{m:>7}" for m in
                                ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                                 "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"])
    print(header)
    for y in years:
        cells = []
        for m in range(1, 13):
            v = by_key.get(f"{y}-{m:02d}")
            cells.append(f"{v * 100:+6.1f}%" if v is not None else "      -")
        print(f"{y}  " + "".join(cells))
    print()
    print(f"Media mensual:      {s['mean'] * 100:+.2f}%   (sobre $10k: ~{s['mean'] * 10000:+,.0f} USDT/mes)")
    print(f"Mediana mensual:    {s['median'] * 100:+.2f}%")
    print(f"Meses positivos:    {s['pct_positive'] * 100:.0f}%")
    print(f"Mejor / peor mes:   {s['best'] * 100:+.1f}% / {s['worst'] * 100:+.1f}%")
    print(f"Racha max negativa: {s['max_neg_streak']} meses")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
