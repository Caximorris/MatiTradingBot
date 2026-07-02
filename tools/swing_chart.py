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

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root {
    --bg:#0d1017; --panel:#14171f; --border:#262b36; --text:#d6dae3;
    --muted:#9aa0ab; --dim:#6f7582; --up:#26a69a; --down:#ef5350;
    --accent:#5b8dee; --gold:#e6b34d;
  }
  html, body { margin:0; padding:0; background:var(--bg); color:var(--text);
               font-family:-apple-system,'Segoe UI',Roboto,sans-serif; }
  #header { padding:12px 24px 8px; border-bottom:1px solid var(--border); }
  .row1 { display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  .row1 h1 { font-size:16px; margin:0; font-weight:600; color:#eceff4; }
  .anchor-cards { display:flex; gap:8px; flex-wrap:wrap; }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:6px;
          padding:4px 12px; text-align:center; }
  .card .lbl { font-size:10px; color:var(--dim); text-transform:uppercase;
               letter-spacing:0.5px; }
  .card .val { font-size:14px; font-weight:600; }
  .pos { color:var(--up); } .neg { color:var(--down); } .neu { color:var(--text); }
  .row2 { margin-top:8px; display:flex; gap:14px; flex-wrap:wrap; align-items:center;
          font-size:12px; color:var(--muted); }
  .row2 .sec b { color:var(--text); font-weight:600; }
  .row3 { margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .preset, #helpbtn { cursor:pointer; background:var(--panel); color:var(--muted);
          border:1px solid var(--border); border-radius:5px; padding:3px 12px;
          font-size:12px; transition: all .12s; }
  .preset:hover, #helpbtn:hover { color:var(--text); border-color:var(--accent); }
  .preset.active { color:#fff; background:var(--accent); border-color:var(--accent); }
  #helpbtn { margin-left:auto; }
  .mk { display:inline-flex; align-items:center; gap:5px; font-size:12px; color:var(--muted); }
  #help { display:none; position:fixed; top:70px; right:20px; width:480px; max-height:76vh;
          overflow-y:auto; background:var(--panel); border:1px solid var(--border);
          border-radius:8px; padding:16px 20px; font-size:12.5px; line-height:1.55;
          z-index:100; box-shadow:0 8px 30px rgba(0,0,0,0.6); }
  #help .close { position:sticky; top:0; float:right; cursor:pointer; color:var(--dim);
                 font-size:18px; line-height:1; background:var(--panel); padding:0 2px; }
  #help .close:hover { color:var(--text); }
  #help h3 { margin:12px 0 4px; font-size:13px; color:#eceff4; }
  #help h3:first-of-type { margin-top:0; }
  #help code { background:#1d222c; padding:1px 5px; border-radius:3px; color:var(--gold);
               font-size:11.5px; }
  #help p { margin:3px 0; color:var(--muted); }
  #chart { width:100vw; height:calc(100vh - 118px); }
</style>
</head>
<body>
<div id="header">
  <div class="row1">
    <h1>__TITLE__</h1>
    <div class="anchor-cards">__ANCHORS__</div>
  </div>
  <div class="row2">__SECONDARY__</div>
  <div class="row3">
    <span style="font-size:11px;color:var(--dim)">RANGO:</span>
    __PRESETS__
    <span style="color:var(--border)">|</span>
    <button class="preset" id="scalebtn" onclick="toggleScale()">Escala: Log</button>
    <button class="preset active" id="bhbtn" onclick="toggleBH()">B&amp;H</button>
    <button class="preset active" id="mkbtn" onclick="toggleMarkers()">Marcadores</button>
    <button class="preset" onclick="resetView()">&#8634; Reset</button>
    <button class="preset" onclick="exportPNG()">&#8681; PNG</button>
    <span class="mk" style="margin-left:12px"><span style="color:var(--up)">&#9650;</span> compra</span>
    <span class="mk"><span style="color:var(--down)">&#9660;</span> venta</span>
    <span class="mk"><span style="color:var(--accent)">&#9670;</span> inicio</span>
    <button id="helpbtn" onclick="toggleHelp()">? Ayuda y glosario</button>
  </div>
</div>
<div id="help">
  <span class="close" onclick="toggleHelp()">&times;</span>
  <h3>Los 4 paneles</h3>
  <p><b>1 &middot; Precio</b> — velas diarias, escala log. El fondo sombreado marca la fase del
     ciclo de halving (verde=post_halving, &aacute;mbar=bull_peak, rojo=bear_onset, sin color=
     accumulation). Cada marcador es un rebalanceo real; su tooltip muestra el cambio de
     allocation y las se&ntilde;ales que lo dispararon.</p>
  <p><b>2 &middot; Allocation</b> — % del portfolio en __BASE__ (el resto en __QUOTE__). Las
     l&iacute;neas de referencia marcan el suelo (20%), el punto neutral (60%) y el techo (100%).
     Esta curva ES la estrategia — todo lo dem&aacute;s es consecuencia.</p>
  <p><b>3 &middot; Equity</b> — valor del portfolio contra Buy &amp; Hold, escala log. La tesis:
     acumular m&aacute;s __BASE__ comprando barato en bear con el __QUOTE__ reservado.</p>
  <p><b>4 &middot; Drawdown</b> — ca&iacute;da desde el &uacute;ltimo m&aacute;ximo de equity. El suelo estructural
     de long-only ~100% en mercado es ~50-53%.</p>
  <h3>Controles</h3>
  <p><b>Rueda del rat&oacute;n</b> — zoom horizontal (tiempo) en los 4 paneles a la vez.</p>
  <p><b>Arrastrar</b> — pan horizontal. Tambi&eacute;n con el slider inferior.</p>
  <p><b>Shift + rueda</b> — zoom vertical (precio o equity, seg&uacute;n el panel).</p>
  <p><b>Shift + arrastrar</b> — pan vertical.</p>
  <p><b>Escala Log/Lineal</b> — cambia los ejes de precio y equity. Log muestra crecimiento
     relativo (un x2 mide igual en 2015 que en 2025); lineal muestra magnitudes absolutas.</p>
  <p><b>B&amp;H / Marcadores</b> — muestra u oculta la l&iacute;nea de Buy &amp; Hold y los
     marcadores de rebalanceo.</p>
  <p><b>Reset</b> — vuelve a la vista completa. <b>PNG</b> — descarga una captura.</p>
  <h3>Glosario de se&ntilde;ales <span style="color:var(--dim);font-weight:normal">
      (las de halving solo aplican a BTC)</span></h3>
  <p><code>regime_bull</code> — EMA50D &gt; EMA200D, precio &gt; EMA200D y ADX &gt; 15. Target +20pp.</p>
  <p><code>regime_bear</code> — EMA50D &lt; EMA200D. Target -20pp.</p>
  <p><code>halving_post_halving</code> / <code>halving_bull_peak</code> — 0-180d / 180-540d tras
     el halving. Target +20pp.</p>
  <p><code>halving_bear_onset</code> — 540-900d tras el halving (distribuci&oacute;n y techo de ciclo).
     Target -30pp y suprime <code>regime_bull</code> (anti ping-pong en lateral).</p>
  <p><code>halving_accumulation</code> — &gt;900d tras el halving. Sin ajuste.</p>
  <p><code>bull_peak_ema50_cap</code> — en bull_peak, si el precio pierde la EMA50D del d&iacute;a
     anterior, el target m&aacute;ximo se capa al 85% (defensa de techo).</p>
  <p><code>init</code> — primera asignaci&oacute;n al arrancar (target neutral 60%).</p>
  <h3>C&oacute;mo funciona el target</h3>
  <p>Base 60% BTC + deltas de las se&ntilde;ales activas, recortado a [20%, 100%]. Solo se
     rebalancea si la diferencia supera 10pp y pasaron &gt;3 d&iacute;as del anterior.</p>
  <h3>C&oacute;mo leer las m&eacute;tricas</h3>
  <p>Anclas de decisi&oacute;n: <b>CAGR</b>, <b>Max DD</b>, <b>Calmar</b> y <b>BTC vs B&amp;H</b>
     (&lt;1.0 = acabas con menos BTC que holdeando). PF y win-rate son m&eacute;tricas contables de
     rebalanceos parciales, NO indicadores de calidad en un allocator.</p>
  <p>Costes: fee 0.1% por fill + slippage seg&uacute;n modo (realistic = 5bps).</p>
</div>
<div id="chart"></div>
<script>
const D = __DATA__;

function toggleHelp(){
  const h = document.getElementById('help');
  h.style.display = h.style.display === 'block' ? 'none' : 'block';
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('help').style.display = 'none';
});

const chart = echarts.init(document.getElementById('chart'), null, {renderer:'canvas'});
window.addEventListener('resize', () => chart.resize());

const UP='#26a69a', DOWN='#ef5350', ACCENT='#5b8dee', GOLD='#e6b34d';
const GRID_LINE='#1d222c', AXIS_TEXT='#9aa0ab', TITLE_TEXT='#6f7582';

// -- indice de fecha mas cercano (para presets y bandas) --
function idxOf(dateStr){
  let lo=0, hi=D.dates.length-1;
  while (lo < hi){ const m=(lo+hi)>>1; if (D.dates[m] < dateStr) lo=m+1; else hi=m; }
  return lo;
}

// -- marcadores de rebalanceo --
const markerColor = {BUY:UP, SELL:DOWN, INIT:ACCENT};
const markers = D.markers.map(m => ({
  value: [m.date, m.price],
  itemStyle: {color: markerColor[m.dir] || GOLD, borderColor:'#0d1017', borderWidth:1},
  symbol: m.dir==='INIT' ? 'diamond' : 'triangle',
  symbolRotate: m.dir==='SELL' ? 180 : 0,
  meta: m,
}));

// -- bandas de fase de halving (markArea sobre el panel de precio) --
const PHASE_STYLE = {
  post_halving: 'rgba(38,166,154,0.07)',
  bull_peak:    'rgba(230,179,77,0.08)',
  bear_onset:   'rgba(239,83,80,0.07)',
  accumulation: 'rgba(255,255,255,0.00)',
};
const phaseAreas = D.phases.filter(p => p.name !== 'accumulation').map(p => [
  {name: p.name, xAxis: D.dates[idxOf(p.from)],
   itemStyle: {color: PHASE_STYLE[p.name]},
   label: {show:true, position:'insideTop', color:TITLE_TEXT, fontSize:10}},
  {xAxis: D.dates[Math.min(idxOf(p.to), D.dates.length-1)]},
]);

// -- data window unificado: mismo indice en todos los paneles --
function fmtMoney(v){
  if (v >= 1e6) return '$' + (v/1e6).toFixed(2) + 'M';
  if (v >= 1e3) return '$' + (v/1e3).toFixed(1) + 'k';
  return '$' + v.toFixed(0);
}
function dataWindow(params){
  const p0 = Array.isArray(params) ? params[0] : params;
  const i = p0.dataIndex;
  if (i == null || !D.dates[i]) return '';
  const c = D.candles[i]; // [open, close, low, high]
  const chg = ((c[1]-c[0])/c[0]*100);
  const chgCls = chg >= 0 ? UP : DOWN;
  const ratio = D.bnh[i] > 0 ? (D.equity[i]/D.bnh[i]) : 0;
  return `<div style="min-width:230px">
    <div style="font-weight:600;margin-bottom:6px">${D.dates[i]}</div>
    <div style="display:grid;grid-template-columns:auto auto;gap:2px 18px;font-size:12px">
      <span style="color:#9aa0ab">Open / Close</span>
      <span>${fmtMoney(c[0])} / <b style="color:${chgCls}">${fmtMoney(c[1])}</b>
        <span style="color:${chgCls}">(${chg>=0?'+':''}${chg.toFixed(1)}%)</span></span>
      <span style="color:#9aa0ab">High / Low</span><span>${fmtMoney(c[3])} / ${fmtMoney(c[2])}</span>
      <span style="color:#9aa0ab">Allocation ${D.base}</span><b style="color:${GOLD}">${D.alloc[i]}%</b>
      <span style="color:#9aa0ab">Equity Swing</span><b style="color:${ACCENT}">${fmtMoney(D.equity[i])}</b>
      <span style="color:#9aa0ab">Buy &amp; Hold</span><span>${fmtMoney(D.bnh[i])} (x${ratio.toFixed(2)})</span>
      <span style="color:#9aa0ab">Drawdown</span><b style="color:${DOWN}">${D.dd[i]}%</b>
    </div></div>`;
}

const option = {
  backgroundColor: '#0d1017',
  animation: false,
  title: [
    {text:'PRECIO ' + D.symbol + ' — velas diarias, escala log'
          + (D.phases.length ? ' · fondo = fase de halving' : ''), top:6},
    {text:'ALLOCATION — % del portfolio en ' + D.base, top:'43.5%'},
    {text:'EQUITY — Swing vs Buy & Hold, escala log', top:'59.5%'},
    {text:'DRAWDOWN — caida desde maximo', top:'83.5%'},
  ].map(t => ({...t, left:70,
               textStyle:{color:TITLE_TEXT, fontSize:10.5, fontWeight:'normal'}})),
  axisPointer: {link: [{xAxisIndex: 'all'}], lineStyle:{color:'#565b66'},
                label: {backgroundColor:'#2a2e39'}},
  tooltip: {
    trigger:'axis', axisPointer:{type:'cross'},
    backgroundColor:'rgba(17,20,28,0.96)', borderColor:'#2a2e39',
    textStyle:{color:'#d6dae3', fontSize:12},
    formatter: dataWindow,
  },
  grid: [
    {left:70, right:80, top:26,      height:'36%'},
    {left:70, right:80, top:'47.5%', height:'10%'},
    {left:70, right:80, top:'63.5%', height:'18%'},
    {left:70, right:80, top:'87.5%', height:'8%'},
  ],
  xAxis: [0,1,2,3].map(i => ({
    type:'category', data:D.dates, gridIndex:i, boundaryGap:i===0,
    axisLine:{lineStyle:{color:'#262b36'}}, axisLabel:{show:i===3, color:AXIS_TEXT},
    axisTick:{show:false}, splitLine:{show:false},
  })),
  yAxis: [
    {gridIndex:0, scale:true, type:'log', logBase:10, position:'right',
     axisLabel:{color:AXIS_TEXT, formatter: v => fmtMoney(v)},
     splitLine:{lineStyle:{color:GRID_LINE}}},
    {gridIndex:1, min:0, max:100, position:'right', interval:20,
     axisLabel:{color:AXIS_TEXT, formatter:'{value}%'},
     splitLine:{lineStyle:{color:GRID_LINE}}},
    {gridIndex:2, scale:true, type:'log', logBase:10, position:'right',
     axisLabel:{color:AXIS_TEXT, formatter: v => fmtMoney(v)},
     splitLine:{lineStyle:{color:GRID_LINE}}},
    {gridIndex:3, max:0, position:'right',
     axisLabel:{color:AXIS_TEXT, formatter:'{value}%'}, splitLine:{show:false}},
  ],
  dataZoom: [
    {type:'inside', xAxisIndex:[0,1,2,3]},
    {type:'slider', xAxisIndex:[0,1,2,3], bottom:4, height:20, left:70, right:80,
     backgroundColor:'#12151d', fillerColor:'rgba(91,141,238,0.14)',
     borderColor:'#262b36', handleStyle:{color:ACCENT},
     textStyle:{color:AXIS_TEXT, fontSize:10},
     dataBackground:{lineStyle:{color:'#3a3f4b'}, areaStyle:{color:'#1a1e27'}}},
    // Zoom/pan VERTICAL (precio y equity): shift+rueda = zoom, shift+arrastrar = pan
    {type:'inside', yAxisIndex:[0], filterMode:'none',
     zoomOnMouseWheel:'shift', moveOnMouseMove:'shift', moveOnMouseWheel:false},
    {type:'inside', yAxisIndex:[2], filterMode:'none',
     zoomOnMouseWheel:'shift', moveOnMouseMove:'shift', moveOnMouseWheel:false},
  ],
  series: [
    {name:'BTC', type:'candlestick', data:D.candles, xAxisIndex:0, yAxisIndex:0,
     itemStyle:{color:UP, color0:DOWN, borderColor:UP, borderColor0:DOWN},
     markArea:{silent:true, data:phaseAreas}},
    {name:'Rebalanceos', type:'scatter', data:markers, xAxisIndex:0, yAxisIndex:0,
     symbolSize:10, z:10,
     tooltip:{trigger:'item', formatter: p => {
       const m = p.data.meta;
       const dirColor = markerColor[m.dir] || GOLD;
       return `<div style="min-width:220px">
         <div style="margin-bottom:4px"><b style="color:${dirColor}">${m.dir}</b>
           <span style="color:#9aa0ab">— ${m.ts} UTC</span></div>
         Precio: <b>${fmtMoney(m.price)}</b><br/>
         Allocation: ${m.before}% &rarr; <b>${m.after}%</b>
           <span style="color:#9aa0ab">(target ${m.target}%)</span><br/>
         Portfolio: ${fmtMoney(m.portfolio)}<br/>
         <span style="color:#9aa0ab;font-size:11px">${m.signals}</span></div>`;
     }}},
    {name:'% BTC', type:'line', data:D.alloc, xAxisIndex:1, yAxisIndex:1,
     step:'end', symbol:'none', lineStyle:{color:GOLD, width:1.5},
     areaStyle:{color:'rgba(230,179,77,0.10)'},
     markLine:{silent:true, symbol:'none',
       lineStyle:{color:'#4a4f5c', type:'dashed', width:1},
       label:{color:TITLE_TEXT, fontSize:10, position:'insideStartTop'},
       data:[{yAxis:20, label:{formatter:'suelo 20%'}},
             {yAxis:60, label:{formatter:'base 60%'}}]}},
    {name:'Swing', type:'line', data:D.equity, xAxisIndex:2, yAxisIndex:2,
     symbol:'none', lineStyle:{color:ACCENT, width:1.8},
     endLabel:{show:true, formatter:'Swing', color:ACCENT, fontSize:11,
               fontWeight:600, distance:4}},
    {name:'Buy & Hold', type:'line', data:D.bnh, xAxisIndex:2, yAxisIndex:2,
     symbol:'none', lineStyle:{color:'#8b93a3', width:1.3, type:'dashed'},
     endLabel:{show:true, formatter:'B&H', color:'#8b93a3', fontSize:11, distance:4}},
    {name:'Drawdown', type:'line', data:D.dd, xAxisIndex:3, yAxisIndex:3,
     symbol:'none', lineStyle:{color:DOWN, width:1},
     areaStyle:{color:'rgba(239,83,80,0.22)'},
     markLine:{silent:true, symbol:'none',
       lineStyle:{color:DOWN, type:'dotted', width:1},
       label:{color:DOWN, fontSize:10, position:'insideStartBottom',
              formatter: p => p.value + '%'},
       data:[{type:'min'}]}},
  ],
};
chart.setOption(option);

// -- presets de rango --
function zoomTo(fromDate, toDate, btn){
  const s = fromDate ? idxOf(fromDate) : 0;
  const e = toDate ? idxOf(toDate) : D.dates.length - 1;
  chart.dispatchAction({type:'dataZoom', dataZoomIndex:0, startValue:s, endValue:e});
  document.querySelectorAll('.row3 .preset').forEach(b => {
    if (b.onclick && b.getAttribute('onclick').startsWith('zoomTo')) b.classList.remove('active');
  });
  if (btn) btn.classList.add('active');
}

// -- escala log / lineal (precio y equity) --
let logScale = true;
function toggleScale(){
  logScale = !logScale;
  const t = logScale ? 'log' : 'value';
  chart.setOption({yAxis: [{type:t}, {}, {type:t}, {}]});
  document.getElementById('scalebtn').textContent = 'Escala: ' + (logScale ? 'Log' : 'Lineal');
  // reset del zoom vertical al cambiar de escala (los rangos no son equivalentes)
  chart.dispatchAction({type:'dataZoom', dataZoomIndex:2, start:0, end:100});
  chart.dispatchAction({type:'dataZoom', dataZoomIndex:3, start:0, end:100});
}

// -- mostrar/ocultar B&H y marcadores --
let showBH = true, showMk = true;
function toggleBH(){
  showBH = !showBH;
  chart.setOption({series: [{}, {}, {}, {}, {data: showBH ? D.bnh : []}, {}]});
  document.getElementById('bhbtn').classList.toggle('active', showBH);
}
function toggleMarkers(){
  showMk = !showMk;
  chart.setOption({series: [{}, {data: showMk ? markers : []}, {}, {}, {}, {}]});
  document.getElementById('mkbtn').classList.toggle('active', showMk);
}

// -- reset de vista completo (x + y) --
function resetView(){
  chart.dispatchAction({type:'dataZoom', dataZoomIndex:0, start:0, end:100});
  chart.dispatchAction({type:'dataZoom', dataZoomIndex:2, start:0, end:100});
  chart.dispatchAction({type:'dataZoom', dataZoomIndex:3, start:0, end:100});
  document.querySelectorAll('.row3 .preset').forEach(b => {
    if (b.getAttribute('onclick') && b.getAttribute('onclick').startsWith('zoomTo'))
      b.classList.toggle('active', b.textContent === 'Todo');
  });
}

// -- exportar PNG --
function exportPNG(){
  const url = chart.getDataURL({pixelRatio:2, backgroundColor:'#0d1017'});
  const a = document.createElement('a');
  a.href = url;
  a.download = 'swing_' + D.symbol.replace('-','') + '_' + D.dates[0] + '_' + D.dates[D.dates.length-1] + '.png';
  a.click();
}
</script>
</body>
</html>
"""


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
    return (HTML_TEMPLATE
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
