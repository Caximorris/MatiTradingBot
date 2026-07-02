"""
Grafico interactivo del Swing Allocator desde un journal de backtest.

Genera un HTML autocontenido (ECharts via CDN, tema oscuro) con 4 paneles
sincronizados: precio+rebalanceos+fases de halving, allocation %, equity
vs B&H (log), drawdown. Data window unificado y presets de rango.

Uso:
    python tools/swing_chart.py                          # ultimo journal swing
    python tools/swing_chart.py backtests/journal_....json
    python tools/swing_chart.py --out mi_grafico.html

La equity se reconstruye desde el journal + cache OHLCV (mismo metodo validado
en tools/audit_equity_recon.py, err <0.05%). No re-ejecuta el backtest.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FEE = 0.001
SLIP_BY_MODE = {"ideal": 0.0, "realistic": 0.0005, "conservative": 0.0015}

# Halvings BTC (SESSION.md). El ultimo es estimado.
HALVINGS = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20", "2028-03-15"]


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

def load_journal(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_bars(cache_path: Path, from_ms: int, to_ms: int) -> list[tuple[int, float, float, float, float]]:
    """Devuelve [(ts_ms, open, high, low, close)] dentro de la ventana."""
    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)
    bars = []
    for r in cache["bars"]:
        ts = int(r[0])
        if from_ms <= ts <= to_ms:
            bars.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    bars.sort()
    return bars


def resample_daily(bars: list) -> list[tuple[str, float, float, float, float]]:
    """1H -> velas diarias UTC: [(fecha, open, high, low, close)]."""
    days: dict[str, list] = {}
    for ts, o, h, l, c in bars:
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if d not in days:
            days[d] = [o, h, l, c]
        else:
            row = days[d]
            row[1] = max(row[1], h)
            row[2] = min(row[2], l)
            row[3] = c
    return [(d, *days[d]) for d in sorted(days)]


# ---------------------------------------------------------------------------
# Reconstruccion de equity (metodo de audit_equity_recon.py)
# ---------------------------------------------------------------------------

def reconstruct(journal: dict, bars: list) -> dict:
    """Series diarias: dates, equity, bnh, alloc_pct, drawdown_pct."""
    slip = SLIP_BY_MODE.get(journal["meta"].get("cost_mode", "realistic"), 0.0005)
    initial = float(journal["statistics"]["initial_balance_usdt"])

    usdt, btc = initial, 0.0
    events = []  # (ts_ms, usdt, btc)
    for r in journal["rebalances"]:
        ts = datetime.fromisoformat(r["timestamp"]).timestamp() * 1000
        p, q = float(r["price"]), float(r["qty"])
        if r["direction"] in ("INIT", "BUY"):
            usdt -= q * p * (1 + slip) * (1 + FEE)
            btc += q
        else:
            usdt += q * p * (1 - slip) * (1 - FEE)
            btc -= q
        events.append((ts, usdt, btc))
    ev_ts = [e[0] for e in events]

    # B&H con coste de entrada (F11)
    p0 = bars[0][4]
    bnh_qty = initial / (p0 * (1 + slip) * (1 + FEE))

    daily: dict[str, tuple[float, float, float]] = {}
    for ts, _o, _h, _l, c in bars:
        i = bisect_right(ev_ts, ts) - 1
        if i < 0:
            eq, alloc = initial, 0.0
        else:
            u, b = events[i][1], events[i][2]
            eq = u + b * c
            alloc = (b * c / eq) if eq > 0 else 0.0
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        daily[d] = (eq, bnh_qty * c, alloc)

    dates = sorted(daily)
    equity = [round(daily[d][0], 2) for d in dates]
    bnh    = [round(daily[d][1], 2) for d in dates]
    alloc  = [round(daily[d][2] * 100, 1) for d in dates]

    peak, dd = equity[0], []
    for eq in equity:
        peak = max(peak, eq)
        dd.append(round((eq - peak) / peak * 100, 2))

    return {"dates": dates, "equity": equity, "bnh": bnh, "alloc": alloc, "dd": dd}


def marker_data(journal: dict) -> list[dict]:
    """Puntos de rebalanceo para el panel de precio, con tooltip completo."""
    out = []
    for r in journal["rebalances"]:
        d = datetime.fromisoformat(r["timestamp"]).strftime("%Y-%m-%d")
        out.append({
            "date":   d,
            "ts":     r["timestamp"][:16].replace("T", " "),
            "dir":    r["direction"],
            "price":  float(r["price"]),
            "before": round(float(r["btc_pct_before"]) * 100, 1),
            "target": round(float(r["btc_pct_target"]) * 100, 1),
            "after":  round(float(r["btc_pct_after"]) * 100, 1),
            "signals": ", ".join(r.get("signals", [])),
            "portfolio": round(float(r["portfolio_usdt"]), 0),
        })
    return out


def phase_bands(journal: dict, from_d: str, to_d: str) -> list[dict]:
    """Bandas de fase de halving dentro de la ventana (solo BTC)."""
    if not journal["meta"]["symbol"].upper().startswith("BTC"):
        return []
    cfg   = journal["meta"].get("resolved_config", {})
    post  = int(cfg.get("phase_post_end", 180))
    peak  = int(cfg.get("phase_peak_end", 540))
    onset = int(cfg.get("phase_onset_end", 900))

    w0 = datetime.strptime(from_d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    w1 = datetime.strptime(to_d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    hs = [datetime.strptime(h, "%Y-%m-%d").replace(tzinfo=timezone.utc) for h in HALVINGS]

    bands = []
    for i, h in enumerate(hs):
        nxt = hs[i + 1] if i + 1 < len(hs) else h + timedelta(days=1600)
        segs = [
            ("post_halving", h,                          h + timedelta(days=post)),
            ("bull_peak",    h + timedelta(days=post),   h + timedelta(days=peak)),
            ("bear_onset",   h + timedelta(days=peak),   h + timedelta(days=onset)),
            ("accumulation", h + timedelta(days=onset),  nxt),
        ]
        for name, a, b in segs:
            a2, b2 = max(a, w0), min(b, w1)
            if a2 < b2:
                bands.append({"name": name,
                              "from": a2.strftime("%Y-%m-%d"),
                              "to":   b2.strftime("%Y-%m-%d")})
    return bands


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML_TEMPLATE_PATH = Path(__file__).with_name("swing_chart_template.html")


def build_presets(dates: list[str]) -> str:
    """Botones de rango: Todo + ciclos de halving presentes en la ventana + ult. 12m."""
    first, last = dates[0], dates[-1]
    cycles = [
        ("Ciclo 2017", "2015-01-01", "2018-12-31"),
        ("Ciclo 2021", "2018-12-01", "2022-12-31"),
        ("Ciclo actual", "2022-12-01", None),
    ]
    btns = ['<button class="preset active" onclick="zoomTo(null,null,this)">Todo</button>']
    for name, a, b in cycles:
        if (b or last) < first or a > last:
            continue
        a_js = f"'{max(a, first)}'"
        b_js = f"'{b}'" if b else "null"
        btns.append(f'<button class="preset" onclick="zoomTo({a_js},{b_js},this)">{name}</button>')
    y1 = (datetime.strptime(last, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    if y1 > first:
        btns.append(f'<button class="preset" onclick="zoomTo(\'{y1}\',null,this)">Ult. 12m</button>')
    return "".join(btns)


def build_html(journal: dict, series: dict, candles: list, markers: list, phases: list) -> str:
    meta, st = journal["meta"], journal["statistics"]
    bt = meta.get("backtest", {})
    parts = meta["symbol"].split("-")
    base  = parts[0].upper()
    quote = parts[1].upper() if len(parts) > 1 else "USDT"
    title = (f"Swing Allocator — {meta['symbol']} "
             f"{meta['from_date']} a {meta['to_date']} · costes {meta['cost_mode']}")

    def money(v):
        v = float(v)
        return f"${v/1e6:.2f}M" if v >= 1e6 else f"${v:,.0f}"

    cagr   = bt.get("cagr_pct")
    dd     = bt.get("max_drawdown_pct")
    sharpe = bt.get("sharpe")
    calmar = (float(cagr) / abs(float(dd))) if cagr and dd and float(dd) != 0 else None
    ratio  = float(st["btc_vs_bnh_ratio"])

    # Anclas de decision: cards destacadas
    anchors = []
    if cagr:
        anchors.append(("CAGR", f"+{float(cagr):.1f}%", "pos"))
    if dd:
        anchors.append(("Max DD", f"-{float(dd):.1f}%", "neg"))
    if calmar:
        anchors.append(("Calmar", f"{calmar:.2f}", "neu"))
    anchors.append((f"{base} vs B&amp;H", f"{ratio}", "pos" if ratio >= 1.0 else "neg"))
    anchors_html = "".join(
        f'<div class="card"><div class="lbl">{lbl}</div>'
        f'<div class="val {cls}">{val}</div></div>'
        for lbl, val, cls in anchors
    )

    # Underwater maximo (peak -> recovery) desde la serie diaria
    uw_max, uw_cur = 0, 0
    for v in series["dd"]:
        uw_cur = uw_cur + 1 if v < 0 else 0
        uw_max = max(uw_max, uw_cur)

    secondary = [
        f'<span class="sec">Final: <b>{money(st["final_balance_usdt"])}</b></span>',
        f'<span class="sec">Sharpe: <b>{float(sharpe):.2f}</b></span>' if sharpe else "",
        f'<span class="sec">Underwater max: <b>{uw_max}d</b></span>' if uw_max else "",
        f'<span class="sec">Rebalanceos: <b>{st["total_rebalances"]}</b></span>',
        f'<span class="sec">{base} medio: <b>{st["avg_btc_pct"]}%</b></span>',
        '<span class="sec" style="color:var(--dim)">PF/WR: contables, no anclas</span>',
    ]

    data = {
        "symbol":  meta["symbol"],
        "base":    base,
        "quote":   quote,
        "dates":   series["dates"],
        "candles": [[o, c, l, h] for _d, o, h, l, c in candles],  # ECharts: [open,close,low,high]
        "alloc":   series["alloc"],
        "equity":  series["equity"],
        "bnh":     series["bnh"],
        "dd":      series["dd"],
        "markers": markers,
        "phases":  phases,
    }
    template = HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    return (template
            .replace("__TITLE__", title)
            .replace("__BASE__", base)
            .replace("__QUOTE__", quote)
            .replace("__ANCHORS__", anchors_html)
            .replace("__SECONDARY__", "".join(secondary))
            .replace("__PRESETS__", build_presets(series["dates"]))
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Grafico HTML interactivo del Swing Allocator")
    ap.add_argument("journal", nargs="?", default=None,
                    help="Ruta al journal JSON (default: ultimo journal_swing_allocator_*)")
    ap.add_argument("--cache", default=None, help="Cache OHLCV (default: data/cache/{symbol}_{tf}.json)")
    ap.add_argument("--out", default=None, help="Ruta HTML de salida (default: backtests/chart_swing_*.html)")
    args = ap.parse_args()

    if args.journal:
        jpath = Path(args.journal)
    else:
        found = sorted(glob.glob(str(ROOT / "backtests" / "journal_swing_allocator_*.json")))
        if not found:
            print("ERROR: no hay journals de swing en backtests/")
            return 1
        jpath = Path(found[-1])

    if not jpath.exists():
        print(f"ERROR: no existe {jpath}")
        return 1

    journal = load_journal(jpath)
    if "rebalances" not in journal:
        print(f"ERROR: {jpath.name} no es un journal de Swing Allocator (sin 'rebalances').")
        print("Esta herramienta visualiza rebalanceos; los journals de trades "
              "(pro_trend, scalp, adaptive) tienen otro formato.")
        return 1
    meta = journal["meta"]
    symbol, tf = meta["symbol"], meta["timeframe"]

    cache_path = Path(args.cache) if args.cache else ROOT / "data" / "cache" / f"{symbol}_{tf}.json"
    if not cache_path.exists():
        print(f"ERROR: no existe el cache {cache_path}")
        return 1

    from_ms = int(datetime.strptime(meta["from_date"], "%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp() * 1000)
    to_ms   = int(datetime.strptime(meta["to_date"], "%Y-%m-%d")
                  .replace(hour=23, minute=59, tzinfo=timezone.utc).timestamp() * 1000)

    print(f"Journal: {jpath.name}")
    bars = load_bars(cache_path, from_ms, to_ms)
    if not bars:
        print("ERROR: el cache no cubre la ventana del journal")
        return 1
    print(f"Velas 1H: {len(bars):,} | reconstruyendo equity...")

    series  = reconstruct(journal, bars)
    candles = resample_daily(bars)
    markers = marker_data(journal)
    phases  = phase_bands(journal, meta["from_date"], meta["to_date"])

    # Sanity: la equity reconstruida debe cuadrar con el journal (<0.5%)
    final_recon = series["equity"][-1]
    final_journal = float(journal["statistics"]["final_balance_usdt"])
    err = abs(final_recon - final_journal) / final_journal if final_journal else 0.0
    print(f"Equity final: reconstruida ${final_recon:,.0f} vs journal ${final_journal:,.0f} "
          f"(err {err:.3%})")
    if err > 0.005:
        print("AVISO: divergencia >0.5% — revisar cost_mode del journal vs cache usado")

    if args.out:
        out = Path(args.out)
    else:
        out = ROOT / "backtests" / jpath.name.replace("journal_", "chart_").replace(".json", ".html")

    out.write_text(build_html(journal, series, candles, markers, phases), encoding="utf-8")
    print(f"OK -> {out}")
    print("Abre el archivo en el navegador (doble clic o 'start' en Windows / 'open' en macOS).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
