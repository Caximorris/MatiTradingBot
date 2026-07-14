"""Graficos PNG para el control remoto Telegram (/equity y /chart).

Reconstruye la curva de equity del paper desde swing_rebalances.jsonl (holdings
constantes entre rebalanceos) y velas 1H publicas de OKX. matplotlib se importa
LAZY y en backend Agg: en la e2-micro (1GB RAM) solo paga memoria al renderizar.

Sin credenciales: solo endpoints publicos de mercado.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# User-Agent obligatorio: el Cloudflare de OKX devuelve 403 al UA de urllib
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_MAX_DAYS = 60          # /market/(history-)candles no da mas profundidad util en 1H
_PAGE_LIMIT = 300       # maximo de OKX por llamada

# Paleta (dataviz reference, superficie clara)
_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_INK_2 = "#52514e"
_GRID = "#e8e7e4"
_AXIS = "#d0cfcb"
_BOT = "#2a78d6"        # serie 1: equity del bot
_BNH = "#1baf7a"        # serie 2: buy & hold
_BUY = "#0ca30c"        # status good
_SELL = "#d03b3b"       # status critical


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_candles(symbol: str = "BTC-USDT", bar: str = "1H",
                  days: int = 30) -> list[tuple[int, float]]:
    """Velas ascendentes [(ts_ms, close)] de los ultimos `days` dias.

    Pagina /market/candles (reciente) y sigue en /market/history-candles si hace
    falta mas profundidad. OKX devuelve nuevas->viejas; aqui se invierte.
    """
    days = max(1, min(days, _MAX_DAYS))
    needed = days * 24
    out: dict[int, float] = {}
    for endpoint in ("candles", "history-candles"):
        after = ""
        while len(out) < needed:
            url = (f"https://www.okx.com/api/v5/market/{endpoint}"
                   f"?instId={symbol}&bar={bar}&limit={_PAGE_LIMIT}{after}")
            rows = _get(url).get("data", [])
            if not rows:
                break
            for r in rows:
                out[int(r[0])] = float(r[4])
            after = f"&after={rows[-1][0]}"
        if len(out) >= needed:
            break
    series = sorted(out.items())[-needed:]
    return [(ts, close) for ts, close in series]


def _rb_ts_ms(rb: dict) -> int:
    return int(datetime.fromisoformat(rb["timestamp"]).timestamp() * 1000)


def build_equity_series(rebalances: list[dict],
                        candles: list[tuple[int, float]]) -> dict:
    """Equity del bot y de B&H BTC por vela, desde el INIT.

    Holdings tras cada rebalanceo: btc = port*pct/precio, usdt = port*(1-pct);
    constantes hasta el siguiente. B&H = todo el portfolio inicial a BTC al
    precio del INIT. Devuelve {ts, bot, bnh, events}; vacio si faltan datos.
    """
    if not rebalances or not candles:
        return {"ts": [], "bot": [], "bnh": [], "events": []}
    rbs = sorted(rebalances, key=_rb_ts_ms)
    init = rbs[0]
    init_port, init_price = float(init.get("portfolio_usdt", 0)), float(init.get("price", 0))
    if init_port <= 0 or init_price <= 0:
        return {"ts": [], "bot": [], "bnh": [], "events": []}
    bnh_qty = init_port / init_price

    holdings: list[tuple[int, float, float]] = []      # (ts_ms, btc_qty, usdt)
    for rb in rbs:
        port, price = float(rb.get("portfolio_usdt", 0)), float(rb.get("price", 0))
        pct = float(rb.get("btc_pct_after", 0))
        if port <= 0 or price <= 0:
            continue
        holdings.append((_rb_ts_ms(rb), port * pct / price, port * (1 - pct)))

    ts_out, bot_out, bnh_out, events = [], [], [], []
    i = -1
    for ts, close in candles:
        if ts < holdings[0][0]:
            continue
        while i + 1 < len(holdings) and holdings[i + 1][0] <= ts:
            i += 1
            rb = rbs[i]
            events.append((ts, float(rb.get("portfolio_usdt", 0)),
                           rb.get("direction", "?")))
        btc_qty, usdt = holdings[i][1], holdings[i][2]
        ts_out.append(ts)
        bot_out.append(btc_qty * close + usdt)
        bnh_out.append(bnh_qty * close)
    return {"ts": ts_out, "bot": bot_out, "bnh": bnh_out, "events": events}


def equity_summary(rebalances: list[dict], series: dict) -> dict[str, float] | None:
    """Final values and INIT-anchored returns, matching Telegram /status semantics."""
    if not rebalances or not series.get("bot") or not series.get("bnh"):
        return None
    init_port = float(rebalances[0].get("portfolio_usdt", 0))
    if init_port <= 0:
        return None
    bot_final = float(series["bot"][-1])
    bnh_final = float(series["bnh"][-1])
    bot_growth = bot_final / init_port
    bnh_growth = bnh_final / init_port
    return {
        "bot_final": bot_final,
        "bnh_final": bnh_final,
        "bot_return_pct": (bot_growth - 1) * 100,
        "bnh_return_pct": (bnh_growth - 1) * 100,
        "bot_bnh_ratio": bot_growth / bnh_growth if bnh_growth else 0.0,
    }


# ---------------------------------------------------------------------------
# Render (matplotlib lazy — solo al pedir un grafico)
# ---------------------------------------------------------------------------

def _fig_ax(title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
    fig.patch.set_facecolor(_SURFACE)
    ax.set_facecolor(_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_AXIS)
    ax.tick_params(colors=_INK_2, labelsize=8)
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=11, color=_INK, pad=12)
    return fig, ax


def _to_png(fig) -> bytes:
    import io
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=_SURFACE)
    plt.close(fig)
    return buf.getvalue()


def _dates(ts_ms: list[int]):
    return [datetime.fromtimestamp(t / 1000, tz=timezone.utc) for t in ts_ms]


def _fmt_dollar_axis(ax):
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))


def _date_axis(ax):
    """Fechas concisas y sin colision (las etiquetas ISO completas se solapan)."""
    import matplotlib.dates as mdates
    locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def _event_markers(ax, events: list[tuple[int, float, str]], y_lookup):
    """Marcadores de rebalanceo: forma + color (BUY ^ verde, SELL v rojo)."""
    for ts, _port, direction in events:
        style = {"BUY": ("^", _BUY), "SELL": ("v", _SELL)}.get(direction)
        if style is None:       # INIT y otros: punto neutro
            style = ("o", _INK_2)
        ax.plot(*y_lookup(ts), style[0], color=style[1], markersize=9,
                markeredgecolor=_SURFACE, markeredgewidth=1.5, zorder=5)


def render_equity_png(series: dict, days: int, label: str = "") -> bytes:
    tag = f" {label}" if label else ""
    fig, ax = _fig_ax(f"Swing{tag} paper — equity vs B&H BTC ({days}d)")
    dates = _dates(series["ts"])
    ax.plot(dates, series["bot"], color=_BOT, linewidth=2, label="Bot", zorder=3)
    ax.plot(dates, series["bnh"], color=_BNH, linewidth=2, label="B&H BTC", zorder=2)

    idx = {t: k for k, t in enumerate(series["ts"])}
    _event_markers(ax, series["events"],
                   lambda ts: ([dates[idx[ts]]], [series["bot"][idx[ts]]]))

    # Etiqueta directa del valor final de cada serie (selectiva, tinta de texto)
    for ys, name in ((series["bot"], "Bot"), (series["bnh"], "B&H")):
        ax.annotate(f"  {name} ${ys[-1]:,.0f}", (dates[-1], ys[-1]),
                    fontsize=8.5, color=_INK, va="center")
    ax.margins(x=0.12)
    _fmt_dollar_axis(ax)
    _date_axis(ax)
    ax.legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=_INK_2)
    return _to_png(fig)


def render_price_png(candles: list[tuple[int, float]],
                     rebalances: list[dict], days: int) -> bytes:
    fig, ax = _fig_ax(f"BTC-USDT 1H con rebalanceos ({days}d)")
    ts = [t for t, _ in candles]
    closes = [c for _, c in candles]
    dates = _dates(ts)
    ax.plot(dates, closes, color=_BOT, linewidth=2, zorder=3)

    lo = ts[0] if ts else 0
    events = [(_rb_ts_ms(rb), float(rb.get("price", 0)), rb.get("direction", "?"))
              for rb in rebalances if _rb_ts_ms(rb) >= lo]

    def nearest(ts_ev):
        k = min(range(len(ts)), key=lambda j: abs(ts[j] - ts_ev))
        return [dates[k]], [events_by_ts[ts_ev]]

    events_by_ts = {e[0]: e[1] for e in events}
    _event_markers(ax, events, nearest)
    if closes:
        ax.annotate(f"  ${closes[-1]:,.0f}", (dates[-1], closes[-1]),
                    fontsize=8.5, color=_INK, va="center")
    ax.margins(x=0.1)
    _fmt_dollar_axis(ax)
    _date_axis(ax)
    return _to_png(fig)
