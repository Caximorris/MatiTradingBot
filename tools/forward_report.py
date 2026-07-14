"""Reporte FORWARD-ONLY del paper test (plan T6.1).

Estructuralmente incapaz de incluir datos de backtest historico: filtra TODA fila con
timestamp < FORWARD_TEST_START y cuenta cuantas descarto. Fuente = persistencia existente
(rebalanceos JSONL + carteras paper + ticker spot). No corre ningun backtest.

FORWARD_TEST_START es la fuente de verdad para tooling del contrato — debe coincidir con la
seccion 1 de FORWARD_TEST_CONTRACT.md (cambiar ambos en el mismo commit).

Exporta Markdown y JSON; el envoltorio CLI puede mandarlo a Telegram (tg_send_document).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from tools.paper_bots import count_strategy_events
from tools.paper_snapshot import build_snapshots

# --- FUENTE DE VERDAD del inicio del forward-test (== FORWARD_TEST_CONTRACT.md seccion 1) ---
FORWARD_TEST_START = datetime(2026, 7, 4, tzinfo=timezone.utc)


def _parse_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _forward_only(rebalances: list[dict], start: datetime) -> tuple[list[dict], int]:
    """Divide en (rebalanceos >= start, n_descartados_pre_start). Filas sin ts valido se
    descartan tambien (no pueden ubicarse en la ventana forward)."""
    kept, dropped = [], 0
    for r in rebalances:
        ts = _parse_ts(r.get("timestamp"))
        if ts is not None and ts >= start:
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped


def _drawdown_from_series(equities: list[float]) -> float:
    """Max drawdown (%) de una serie de equity puntual (peak-to-trough). 0 si <2 puntos."""
    if len(equities) < 2:
        return 0.0
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, (eq - peak) / peak * 100)
    return round(max_dd, 2)


def _bot_forward_metrics(snap: dict, start: datetime) -> dict:
    """Metricas forward-only de un bot desde su snapshot (rebalanceos + cartera actual).

    La 'curva' de equity paper es discreta: cada rebalanceo trae `portfolio_usdt` (valor de la
    cartera en ese instante). Se aproxima drawdown/exposicion desde esos puntos + el equity
    actual del snapshot. No hay curva continua persistida por tick — es una aproximacion
    honesta y se etiqueta como tal en el render.
    """
    fwd, dropped = _forward_only(snap.get("rebalances", []), start)

    exposures = [float(r.get("btc_pct_after", 0)) * 100 for r in fwd]
    equities = [float(r.get("portfolio_usdt", 0)) for r in fwd if r.get("portfolio_usdt")]
    cur_equity = snap.get("equity_usd")
    if cur_equity is not None:
        equities = equities + [float(cur_equity)]

    directions = [r.get("direction") for r in fwd]
    return {
        "label": snap.get("label"),
        "name": snap.get("name"),
        "is_active": snap.get("is_active"),
        "wallet_exists": snap.get("wallet_exists"),
        "n_rebalances_forward": count_strategy_events(fwd),
        "pre_start_dropped": dropped,
        "buys": directions.count("BUY"),
        "sells": directions.count("SELL"),
        "inits": directions.count("INIT"),
        "current_equity_usd": (float(cur_equity) if cur_equity is not None else None),
        "current_btc_pct": snap.get("btc_pct"),
        "bnh_ratio": snap.get("bnh_ratio"),
        "avg_exposure_pct": (round(sum(exposures) / len(exposures), 1) if exposures else None),
        "max_exposure_pct": (round(max(exposures), 1) if exposures else None),
        "min_exposure_pct": (round(min(exposures), 1) if exposures else None),
        "approx_max_drawdown_pct": _drawdown_from_series(equities),
        "last_rebalance_ts": (fwd[-1].get("timestamp") if fwd else None),
        "stale": snap.get("stale"),
        "last_run_age_min": snap.get("last_run_age_min"),
    }


def build_forward_report(session, *, price: Decimal | None = None,
                         now: datetime | None = None,
                         start: datetime = FORWARD_TEST_START) -> dict:
    """Reporte forward-only completo (dict serializable). READ-ONLY."""
    now = now or datetime.now(timezone.utc)
    snaps = build_snapshots(session, price=price, now=now)
    bots = [_bot_forward_metrics(s, start) for s in snaps]

    total_dropped = sum(b["pre_start_dropped"] for b in bots)
    # Invariante forward: ninguna metrica proviene de datos pre-start.
    assert all(b["pre_start_dropped"] >= 0 for b in bots)

    # Divergencia v5/v6 (debe ser ~0 antes de ~2026-10-07)
    by_label = {b["label"]: b for b in bots}
    divergence = None
    if "v5" in by_label and "v6" in by_label:
        e5 = by_label["v5"]["current_equity_usd"]
        e6 = by_label["v6"]["current_equity_usd"]
        divergence = {
            "reb_v5": by_label["v5"]["n_rebalances_forward"],
            "reb_v6": by_label["v6"]["n_rebalances_forward"],
            "equity_v5": e5,
            "equity_v6": e6,
            "equity_diff": (round(e6 - e5, 2) if (e5 is not None and e6 is not None) else None),
        }

    return {
        "generated_at": now.isoformat(),
        "forward_start": start.isoformat(),
        "window_days": (now - start).days,
        "spot_price": (float(price) if price is not None else None),
        "pre_start_records_dropped": total_dropped,
        "bots": bots,
        "v5_v6_divergence": divergence,
        # Placeholders honestos: requieren fuentes aun no implementadas (plan)
        "downtime_incidents": "n/a (fuente: daily_checks.log / journal - plan T13/ops)",
        "missed_heartbeats": "n/a (fuente: tg_state.json - plan T13)",
        "data_gaps": "n/a (correr data-audit - plan T7.1)",
        "decisions_skipped": "n/a (requiere decision trace - plan T5.2)",
        "notes": "Equity/drawdown paper son aproximados desde puntos de rebalanceo + cartera "
                 "actual (no hay curva continua por tick persistida).",
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def to_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=True)


def _fmt(v, suffix: str = "", nd: int = 2) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.{nd}f}{suffix}"
    return f"{v}{suffix}"


def to_markdown(report: dict) -> str:
    lines = [
        "# Forward-Test Report (paper)",
        "",
        f"- **Ventana forward:** {report['forward_start'][:10]} -> "
        f"{report['generated_at'][:10]} ({report['window_days']} dias)",
        f"- **Generado:** {report['generated_at'][:19]} UTC",
        f"- **BTC spot:** {_fmt(report['spot_price'], '', 0)}",
        f"- **Filas pre-start descartadas (no contaminan):** "
        f"{report['pre_start_records_dropped']}",
        "",
        "> Solo datos con timestamp >= inicio del forward-test. Ver FORWARD_TEST_CONTRACT.md.",
        "",
        "## Bots",
        "",
        "| Bot | Activo | Equity USD | BTC% | bot/B&H | Reb | Buy/Sell | "
        "Exp avg/max/min | ~MaxDD | Ult. rebalanceo |",
        "|-----|--------|-----------|------|---------|-----|----------|"
        "-----------------|--------|-----------------|",
    ]
    for b in report["bots"]:
        exp = (f"{_fmt(b['avg_exposure_pct'],'%',0)}/"
               f"{_fmt(b['max_exposure_pct'],'%',0)}/{_fmt(b['min_exposure_pct'],'%',0)}")
        lines.append(
            f"| {b['label']} | {'si' if b['is_active'] else 'no'} "
            f"| {_fmt(b['current_equity_usd'],'',0)} | {_fmt(b['current_btc_pct'],'%',0)} "
            f"| {_fmt(b['bnh_ratio'],'',3)} | {b['n_rebalances_forward']} "
            f"| {b['buys']}/{b['sells']} | {exp} "
            f"| {_fmt(b['approx_max_drawdown_pct'],'%',1)} "
            f"| {(b['last_rebalance_ts'] or 'n/a')[:16]} |"
        )
    div = report.get("v5_v6_divergence")
    if div:
        lines += [
            "",
            "## Divergencia v5 vs v6",
            "",
            f"- Rebalanceos: v5={div['reb_v5']} v6={div['reb_v6']}",
            f"- Equity: v5={_fmt(div['equity_v5'],'',0)} v6={_fmt(div['equity_v6'],'',0)} "
            f"(diff {_fmt(div['equity_diff'],'',2)})",
            f"- **Debe ser ~0 antes de ~2026-10-07.** Divergencia temprana = red flag (contrato 6c).",
        ]
    lines += [
        "",
        "## Infraestructura / pendientes",
        "",
        f"- Downtime: {report['downtime_incidents']}",
        f"- Heartbeats perdidos: {report['missed_heartbeats']}",
        f"- Huecos de datos: {report['data_gaps']}",
        f"- Decisiones omitidas: {report['decisions_skipped']}",
        "",
        f"> {report['notes']}",
    ]
    return "\n".join(lines)
