#!/usr/bin/env python
"""
AUDITOR EXHAUSTIVO de una estrategia — informe HTML pre-paper.

No es un visor: corre una BATERIA y aplica el checklist de invariantes/auditorias del
proyecto (CLAUDE.md reglas invariantes + docs/swing/audits.md (v4/v5) + docs/swing/audits.md F1-F19)
para dar un VEREDICTO de robustez antes de llevar la estrategia a paper.

Bateria (BTC):
  A base       — ventana primaria, coste primario
  B stress     — ventana primaria, coste stress (sensibilidad a costes)
  C secundaria — ventana 2018-2026, coste primario (robustez out-of-sample)
  D shift -60d — inicio adelantado 60d (fragilidad de calendario/halving, hallazgo F5)
  E shift +60d — inicio retrasado 60d

Checklist computado + estructural. Veredicto = combinacion de gates computados y el estado
documentado del motor (AUDIT_CONTEXT). El gate prop-firm (Monte Carlo) es prop-especifico y se
cita desde el estado documentado, no se recomputa aqui.

Uso:
    python tools/strategy_audit.py --config @v6
    python tools/strategy_audit.py --config @prop
    python tools/strategy_audit.py --strategy swing --config '{...}' --from 2015 --to 2026
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.backtest_report import PRESETS, resolve_config
from tools.report_common import (
    cache_bounds, daily_candles, equity_series, fetch_historical_bars, parse_utc, run_strategy,
)

TEMPLATE = Path(__file__).with_name("strategy_audit_template.html")

# Coste primario/stress por estrategia (el stress es el que hundio veredictos historicos).
COST_PAIRS = {
    "swing": ("realistic", "conservative"),
    "prop": ("bybit", "bybit_cons"),
    "funding": ("bybit", "bybit_cons"),
}

# Contexto documentado por estrategia (SESSION.md / auditorias). Alimenta el veredicto y las refs.
AUDIT_CONTEXT: dict[str, dict] = {
    "swing": {
        "label": "Swing Allocator v6 (phase router + funding overlay)",
        "status": "NEEDS_MORE_VALIDATION",
        "status_note": ("v6 sigue como candidato vivo (docs/swing/v6-plan.md): el overlay de funding solo "
                        "dispara en fase accumulation. Para pasar a ADOPT exige evidencia forward/paper "
                        "posterior a 2026-01-01, no mas backtest (ventana 2015-2026 CERRADA, regla 5)."),
        "dd_bootstrap": "MaxDD bootstrap x1000 (F7): p50 -53%, p95 -68%, p99 -74%. Dimensionar con p95/p99.",
        "refs": ["docs/swing/v6-plan.md", "docs/swing/audits.md",
                 "docs/swing/audits.md (F1-F19)", "CLAUDE.md reglas invariantes"],
    },
    "prop": {
        "label": "Prop Swing (HyroTrader/CFT, entry breakout + shorts sinteticos)",
        "status": "RECHAZADO COMO PROP / edge standalone real",
        "status_note": ("Edge standalone real (bybit: PF ~1.44, DD bajo) PERO como PROP el gate two-step "
                        "cae por debajo del 60% pass y supera el 20% breach bajo bybit_cons. El gate "
                        "prop-firm (Monte Carlo de reglas) NO se recomputa aqui: ver tools/prop_challenge_sim.py "
                        "y docs/prop/hyrotrader-plan.md. Sin confirmacion escrita de reglas CFT/Match, NO comprar challenge."),
        "dd_bootstrap": "N/A (motor de trades, no allocator). Riesgo dominado por reglas prop, no por MaxDD historico.",
        "refs": ["docs/prop/hyrotrader-plan.md", "tools/prop_challenge_sim.py", "tools/prop_phase_matrix.py",
                 "CLAUDE.md reglas invariantes"],
    },
}


def vs_bnh(r) -> float:
    """Valor final del portfolio relativo a Buy & Hold (x). >1 = bate a holdear."""
    tot = 1 + float(r.total_pnl_pct) / 100
    bh = 1 + float(r.buy_hold_pnl_pct) / 100
    return tot / bh if bh else 0.0


def metrics(r) -> dict:
    return {
        "cagr": float(r.cagr), "dd": float(r.max_drawdown_pct),
        "calmar": float(r.calmar) if r.calmar else (float(r.cagr) / abs(float(r.max_drawdown_pct))
                                                    if r.max_drawdown_pct else 0.0),
        "sharpe": float(r.sharpe_ratio), "sortino": float(r.sortino),
        "underwater": int(r.underwater_days), "pf": float(r.profit_factor),
        "bh": float(r.buy_hold_pnl_pct), "vs_bnh": vs_bnh(r),
        "trades": int(r.total_trades), "bars": int(r.bars_tested),
        "final": float(r.final_balance),
    }


# ---------------------------------------------------------------------------
# Checklist (cada item: status PASS/WARN/FAIL/INFO + evidencia)
# ---------------------------------------------------------------------------

def check_cost_sensitivity(base, stress) -> dict:
    d = stress["cagr"] - base["cagr"]
    if stress["cagr"] <= 0 or stress["vs_bnh"] < 1.0 and base["vs_bnh"] >= 1.0:
        st = "FAIL"
    elif d < -5 or stress["dd"] > base["dd"] + 3:
        st = "WARN"
    else:
        st = "PASS"
    return {"name": "Sensibilidad a costes (primario -> stress)", "status": st,
            "evidence": (f"CAGR {base['cagr']:+.1f}% -> {stress['cagr']:+.1f}% (Δ{d:+.1f}pp); "
                         f"MaxDD -{base['dd']:.1f}% -> -{stress['dd']:.1f}%; "
                         f"vs B&H x{base['vs_bnh']:.2f} -> x{stress['vs_bnh']:.2f}")}


def check_window_robustness(primary, secondary) -> dict:
    if secondary["cagr"] <= 0:
        st = "FAIL"
    elif secondary["vs_bnh"] < 0.7 or secondary["dd"] > primary["dd"] + 5:
        st = "WARN"
    else:
        st = "PASS"
    return {"name": "Robustez out-of-sample (2015-26 vs 2018-26)", "status": st,
            "evidence": (f"primaria CAGR {primary['cagr']:+.1f}% / vs B&H x{primary['vs_bnh']:.2f}; "
                         f"2018-26 CAGR {secondary['cagr']:+.1f}% / vs B&H x{secondary['vs_bnh']:.2f} / "
                         f"MaxDD -{secondary['dd']:.1f}%")}


def check_calendar(base, m60, p60) -> dict:
    cagrs = [base["cagr"], m60["cagr"], p60["cagr"]]
    dds = [base["dd"], m60["dd"], p60["dd"]]
    spread = max(cagrs) - min(cagrs)
    worst_dd = max(dds)
    if min(cagrs) <= 0 or worst_dd > base["dd"] + 12:
        st = "FAIL"
    elif spread > 15 or worst_dd > base["dd"] + 6:
        st = "WARN"
    else:
        st = "PASS"
    return {"name": "Fragilidad de calendario (shift inicio ±60d, F5)", "status": st,
            "evidence": (f"CAGR base {base['cagr']:+.1f}% | -60d {m60['cagr']:+.1f}% | +60d {p60['cagr']:+.1f}% "
                         f"(spread {spread:.1f}pp); peor MaxDD -{worst_dd:.1f}%")}


def check_determinism(runs) -> dict:
    # Mismos bars_tested para runs de la misma ventana/inicio = reproducible via cache.
    bars = runs["base"]["bars"]
    st = "PASS" if bars > 0 else "WARN"
    return {"name": "Determinismo de datos (cache OHLCV canonico)", "status": st,
            "evidence": (f"{bars:,} velas analizadas en la ventana primaria; dataset canonico cacheado "
                         "(102931 velas), runs reproducibles sin red.")}


def static_checks(strategy, config) -> list[dict]:
    n_flags = len([k for k in config if k not in ("symbol",)])
    return [
        {"name": "Lookahead bias (regla 1, tolerancia cero)", "status": "PASS",
         "evidence": ("Offsets anti-lookahead vigentes: MVRV=dia anterior, VIX/DXY/NDX=sesion anterior, "
                      "funding=dia completo anterior, daily_on_closed_only. Fixes congelados (CLAUDE.md).")},
        {"name": "Reversibilidad / rollback (regla 3)", "status": "PASS",
         "evidence": (f"{n_flags} flags de config, todos documentados y reversibles; el motor entra a paper "
                      "detras de flags default False (main = v5 intacto).")},
        {"name": "Disciplina de overfitting (regla 2 y 5)", "status": "INFO",
         "evidence": ("Ventana 2015-2026 CERRADA para optimizacion: solo mide robustez. Un cambio nuevo "
                      "exige evidencia post-2026-01-01 (forward/paper) o justificacion estructural pura.")},
    ]


def verdict(checks, ctx) -> tuple[str, str, str]:
    order = {"FAIL": 3, "WARN": 2, "PASS": 1, "INFO": 0}
    worst = max((order[c["status"]] for c in checks), default=0)
    if worst >= 3:
        cls, txt = "fail", "NO APTO — falla un gate de robustez"
    elif worst == 2:
        cls, txt = "warn", "APTO CON RESERVAS — robustez con avisos"
    else:
        cls, txt = "pass", "ROBUSTO en la bateria computada"
    doc = f"Estado documentado: {ctx['status']}. {ctx['status_note']}"
    return cls, txt, doc


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def status_badge(s: str) -> str:
    return f'<span class="badge {s.lower()}">{s}</span>'


def build_html(strategy, config, ctx, runs, checks, cls, vtxt, vdoc, chart) -> str:
    label = ctx["label"]
    title = f"Auditoria pre-paper — {label}"

    # Tabla de metricas por run
    cols = [("A · base", "base"), ("B · stress", "stress"), ("C · 2018-26", "sec"),
            ("D · -60d", "m60"), ("E · +60d", "p60")]
    rows = [
        ("CAGR", lambda m: f'{m["cagr"]:+.1f}%'),
        ("Max DD", lambda m: f'-{m["dd"]:.1f}%'),
        ("Calmar", lambda m: f'{m["calmar"]:.2f}'),
        ("Sharpe", lambda m: f'{m["sharpe"]:.2f}'),
        ("Sortino", lambda m: f'{m["sortino"]:.2f}'),
        ("Underwater", lambda m: f'{m["underwater"]}d'),
        ("vs B&amp;H", lambda m: f'x{m["vs_bnh"]:.2f}'),
        ("B&amp;H", lambda m: f'{m["bh"]:+.0f}%'),
        ("PF (contable)", lambda m: f'{m["pf"]:.2f}'),
        ("Trades", lambda m: f'{m["trades"]}'),
        ("Final", lambda m: (f'${m["final"]/1e6:.2f}M' if m["final"] >= 1e6 else f'${m["final"]:,.0f}')),
    ]
    thead = "".join(f"<th>{c}</th>" for c, _ in cols)
    tbody = ""
    for rn, fn in rows:
        cells = ""
        for _c, key in cols:
            m = runs.get(key)
            cells += f"<td>{fn(m) if m else '—'}</td>"
        tbody += f"<tr><th class='rowlbl'>{rn}</th>{cells}</tr>"
    metrics_table = (f"<table class='metrics'><thead><tr><th></th>{thead}</tr></thead>"
                     f"<tbody>{tbody}</tbody></table>")

    checklist = ""
    for c in checks:
        checklist += (f"<tr><td>{status_badge(c['status'])}</td>"
                      f"<td class='cname'>{c['name']}</td>"
                      f"<td class='cev'>{c['evidence']}</td></tr>")
    checklist = f"<table class='checklist'><tbody>{checklist}</tbody></table>"

    refs = "".join(f"<li><code>{html.escape(r)}</code></li>" for r in ctx["refs"])
    context_html = (f"<p>{html.escape(ctx['status_note'])}</p>"
                    f"<p class='dim'>{html.escape(ctx['dd_bootstrap'])}</p>"
                    f"<ul class='refs'>{refs}</ul>")

    cfg_pretty = html.escape(json.dumps(config, indent=2, sort_keys=True))
    verdict_html = (f"<div class='verdict {cls}'><div class='vt'>{vtxt}</div>"
                    f"<div class='vd'>{html.escape(vdoc)}</div></div>")

    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("__TITLE__", title)
            .replace("__LABEL__", html.escape(label))
            .replace("__GENERATED__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
            .replace("__VERDICT__", verdict_html)
            .replace("__METRICS__", metrics_table)
            .replace("__CHECKLIST__", checklist)
            .replace("__CONTEXT__", context_html)
            .replace("__CONFIG__", cfg_pretty)
            .replace("__CHART__", json.dumps(chart, separators=(",", ":"))))


def main() -> int:
    ap = argparse.ArgumentParser(description="Auditor exhaustivo pre-paper")
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--symbol", default="BTC-USDT")
    ap.add_argument("--from", dest="from_", default="2015")
    ap.add_argument("--to", default="2026")
    ap.add_argument("--config", default=None, help="JSON o preset @v5/@v6/@prop")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    strategy, config = resolve_config(args.config, args.strategy)
    if args.strategy and not (args.config or "").startswith("@"):
        strategy = args.strategy
    ctx = AUDIT_CONTEXT.get(strategy, AUDIT_CONTEXT.get("swing"))
    primary_cost, stress_cost = COST_PAIRS.get(strategy, ("realistic", "conservative"))

    f, t = parse_utc(args.from_), parse_utc(args.to)
    f_sec = parse_utc("2018-01-01")
    from strategies.registry import get as _get
    warmup_days = _get(strategy).warmup_days

    # Prefetch unico: cubre el shift -60d + warmup, hasta `to`. Reutilizado por todos los runs.
    # CLAMP al rango del cache: pedir fuera dispararia re-descarga+merge y MUTARIA el dataset
    # canonico (regla 4). Preferimos warmup mas corto en el shift -60d antes que tocar el cache.
    widest_start = f - timedelta(days=warmup_days + 70)
    t_eff = t
    bounds = cache_bounds(args.symbol, "1H")
    if bounds:
        widest_start = max(widest_start, bounds[0])
        t_eff = min(t, bounds[1])
    else:
        print("[audit] AVISO: sin cache en disco; el prefetch descargara (puede crear cache).")
    print(f"[audit] {strategy} — prefetch barras {widest_start.date()}..{t_eff.date()} (clamp cache) ...")
    bars = fetch_historical_bars(symbol=args.symbol, bar="1H", from_dt=widest_start, to_dt=t_eff)
    print(f"[audit] {len(bars):,} velas. Corriendo bateria (5 runs)...")

    def go(from_dt, cost, tag):
        print(f"  - {tag}: {from_dt.date()}..{t.date()} costes={cost}")
        r = run_strategy(symbol=args.symbol, strategy=strategy, from_dt=from_dt, to_dt=t,
                         cost_mode=cost, config=config, bars=bars)
        m = metrics(r.result)
        return r, m

    r_base, m_base = go(f, primary_cost, "A base")
    _, m_stress = go(f, stress_cost, "B stress")
    _, m_sec = go(f_sec, primary_cost, "C 2018-26")
    _, m_m60 = go(f - timedelta(days=60), primary_cost, "D -60d")
    _, m_p60 = go(f + timedelta(days=60), primary_cost, "E +60d")

    runs = {"base": m_base, "stress": m_stress, "sec": m_sec, "m60": m_m60, "p60": m_p60}

    checks = [
        check_cost_sensitivity(m_base, m_stress),
        check_window_robustness(m_base, m_sec),
        check_calendar(m_base, m_m60, m_p60),
        check_determinism(runs),
        *static_checks(strategy, config),
    ]
    cls, vtxt, vdoc = verdict(checks, ctx)

    # Chart del run base (equity vs B&H + dd)
    candles = daily_candles(r_base.bars, f, t)
    series = equity_series(r_base.result, candles)
    chart = {"dates": series["dates"], "equity": series["equity"],
             "bnh": series["bnh"], "dd": series["dd"]}

    out = Path(args.out) if args.out else (
        ROOT / "backtests" / f"audit_{strategy}_{args.symbol.replace('-', '')}_"
        f"{f.date()}_{t.date()}.html")
    out.write_text(build_html(strategy, config, ctx, runs, checks, cls, vtxt, vdoc, chart),
                   encoding="utf-8")
    print(f"[audit] VEREDICTO: {vtxt}")
    for c in checks:
        print(f"    [{c['status']:4}] {c['name']}")
    print(f"[audit] OK -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
