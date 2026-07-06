#!/usr/bin/env python
"""
Visor HTML GENERICO de backtests — cualquier estrategia del registry.

A diferencia de tools/swing_chart.py (solo allocators, lee un journal), este re-ejecuta
el backtest de la estrategia elegida y renderiza 3 paneles sincronizados (precio+marcadores,
equity vs Buy & Hold en log, drawdown) desde result.equity_curve. Agnostico al formato:
los marcadores salen de _rebalance_log (allocators) o _journal (estrategias de trades).

Uso:
    python tools/backtest_report.py --strategy prop  --from 2018 --to 2026 --costs bybit \\
        --config '{"entry_mode":"breakout","risk_per_trade":0.018,"allow_shorts":true,...}'
    python tools/backtest_report.py --strategy swing --from 2015 --to 2026 --config @v6
    python tools/backtest_report.py --strategy pro   --from 2018 --to 2026 --out mi.html

`--config @v6` y `@prop` son presets canonicos de paper (ver PRESETS abajo).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.report_common import (
    daily_candles, equity_series, extract_markers, parse_utc, phase_bands, run_strategy,
)

TEMPLATE = Path(__file__).with_name("backtest_report_template.html")

# Presets canonicos = exactamente lo que se registra en paper (tools/*_setup.py).
PRESETS: dict[str, tuple[str, dict]] = {
    "v6": ("swing", {
        "use_phase_policy_router": True, "phase_policy_profile": "v5_equiv",
        "use_funding_overlay": True, "funding_overlay_phases": "accumulation",
        "funding_overlay_delta": 0.05, "funding_low_pctile": 0.10,
        "funding_high_pctile": 0.90, "funding_overlay_ttl_days": 7,
        "funding_overlay_dedup_days": 7,
    }),
    "v5": ("swing", {}),
    "prop": ("prop", {
        "entry_mode": "breakout", "risk_per_trade": 0.018, "tp1_r": 1.5,
        "allow_shorts": True, "max_notional_pct": 0.8, "model_funding": True,
        "entry_halving_phases": "bear_onset,accumulation",
    }),
}


def resolve_config(raw: str | None, strategy: str | None) -> tuple[str, dict]:
    if raw and raw.startswith("@"):
        key = raw[1:]
        if key not in PRESETS:
            raise SystemExit(f"preset desconocido '{raw}'. Disponibles: {list(PRESETS)}")
        return PRESETS[key]
    return strategy or "swing", (json.loads(raw) if raw else {})


def build_presets_html(dates: list[str]) -> str:
    first, last = dates[0], dates[-1]
    btns = ['<button class="preset active" onclick="zoomTo(null,null,this)">Todo</button>']
    for name, a, b in [("Ciclo 2021", "2018-12-01", "2022-12-31"),
                       ("Ciclo actual", "2022-12-01", None)]:
        if (b or last) < first or a > last:
            continue
        a_js = f"'{max(a, first)}'"
        b_js = f"'{b}'" if b else "null"
        btns.append(f'<button class="preset" onclick="zoomTo({a_js},{b_js},this)">{name}</button>')
    y1 = (datetime.strptime(last, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    if y1 > first:
        btns.append(f'<button class="preset" onclick="zoomTo(\'{y1}\',null,this)">Ult. 12m</button>')
    return "".join(btns)


def build_html(run, series, candles, markers, kind) -> str:
    r = run.result
    base = run.symbol.split("-")[0].upper()
    title = (f"{r.strategy_name} · {run.symbol} · {run.from_dt.date()} a "
             f"{run.to_dt.date()} · costes {run.cost_mode}")

    cagr = float(r.cagr)
    dd = float(r.max_drawdown_pct)
    calmar = float(r.calmar) if r.calmar else (cagr / abs(dd) if dd else 0.0)
    final_eq = series["equity"][-1] if series["equity"] else float(r.final_balance)
    final_bnh = series["bnh"][-1] if series["bnh"] else 0.0
    vs_bnh = (final_eq / final_bnh) if final_bnh else 0.0

    def money(v):
        v = float(v)
        return f"${v/1e6:.2f}M" if v >= 1e6 else f"${v:,.0f}"

    anchors = [
        ("CAGR", f"{cagr:+.1f}%", "pos" if cagr >= 0 else "neg"),
        ("Max DD", f"-{dd:.1f}%", "neg"),
        ("Calmar", f"{calmar:.2f}", "neu"),
        ("vs B&amp;H", f"x{vs_bnh:.2f}", "pos" if vs_bnh >= 1 else "neg"),
    ]
    anchors_html = "".join(
        f'<div class="card"><div class="lbl">{l}</div><div class="val {c}">{v}</div></div>'
        for l, v, c in anchors)

    n_exits = sum(1 for m in markers if m["kind"] == "exit")
    label_ops = "rebalanceos" if kind == "allocator" else "trades"
    n_ops = len(markers) if kind == "allocator" else n_exits
    secondary = [
        f'<span class="sec">Final: <b>{money(final_eq)}</b></span>',
        f'<span class="sec">Sharpe: <b>{float(r.sharpe_ratio):.2f}</b></span>',
        f'<span class="sec">Sortino: <b>{float(r.sortino):.2f}</b></span>',
        f'<span class="sec">Underwater max: <b>{r.underwater_days}d</b></span>',
        f'<span class="sec">B&amp;H: <b>{float(r.buy_hold_pnl_pct):+.0f}%</b></span>',
        f'<span class="sec">{label_ops}: <b>{n_ops}</b></span>',
        f'<span class="sec">PF: <b>{float(r.profit_factor):.2f}</b> '
        f'<span style="color:var(--dim)">(contable)</span></span>',
        f'<span class="sec">velas: <b>{r.bars_tested:,}</b></span>',
    ]

    data = {
        "symbol": run.symbol, "base": base, "kind": kind,
        "dates": series["dates"],
        "candles": [[o, c, l, h] for _d, o, h, l, c in candles],  # ECharts [open,close,low,high]
        "equity": series["equity"], "bnh": series["bnh"], "dd": series["dd"],
        "markers": markers,
        "phases": phase_bands(run.symbol, run.from_dt, run.to_dt, run.config),
    }
    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("__TITLE__", title)
            .replace("__ANCHORS__", anchors_html)
            .replace("__SECONDARY__", "".join(secondary))
            .replace("__PRESETS__", build_presets_html(series["dates"]))
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))


def main() -> int:
    ap = argparse.ArgumentParser(description="Visor HTML generico de backtests")
    ap.add_argument("--strategy", default=None, help="alias del registry (swing/pro/prop/scalp/...)")
    ap.add_argument("--symbol", default="BTC-USDT")
    ap.add_argument("--from", dest="from_", default="2018")
    ap.add_argument("--to", default="2026")
    ap.add_argument("--costs", default="realistic")
    ap.add_argument("--timeframe", default="1H")
    ap.add_argument("--config", default=None, help="JSON o preset @v5/@v6/@prop")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    strategy, config = resolve_config(args.config, args.strategy)
    if args.strategy and not (args.config or "").startswith("@"):
        strategy = args.strategy
    f, t = parse_utc(args.from_), parse_utc(args.to)

    print(f"Ejecutando {strategy} {args.symbol} {f.date()}..{t.date()} costes={args.costs} ...")
    run = run_strategy(symbol=args.symbol, strategy=strategy, from_dt=f, to_dt=t,
                       cost_mode=args.costs, config=config, timeframe=args.timeframe)
    candles = daily_candles(run.bars, f, t)
    series = equity_series(run.result, candles)
    markers, kind = extract_markers(run.strategy)
    print(f"  CAGR {float(run.result.cagr):+.1f}% | DD -{float(run.result.max_drawdown_pct):.1f}% | "
          f"{len(markers)} marcadores ({kind}) | {len(candles)} velas diarias")

    out = Path(args.out) if args.out else (
        ROOT / "backtests" / f"report_{strategy}_{args.symbol.replace('-', '')}_"
        f"{f.date()}_{t.date()}_{args.costs}.html")
    out.write_text(build_html(run, series, candles, markers, kind), encoding="utf-8")
    print(f"OK -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
