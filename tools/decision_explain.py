"""Decision Explanation View (plan T5.1, docs/forward-test/research-lab-plan.md §5).

Explica en texto plano UN rebalanceo YA EJECUTADO leyendo unicamente lo que
strategies/swing_allocator.py._log_rebalance ya persiste en swing_rebalances.jsonl. No
importa la logica de trading, no reconstruye decisiones SKIPPED (eso es T5.2, bloqueado hasta
revision de aislamiento) y no muta nada.

Gap conocido (documentado en el plan): el journal actual no guarda cooldown ni el umbral de
rebalanceo, asi que este modulo no puede explicar "por que no hubo rebalanceo" — solo el que
ya paso.
"""
from __future__ import annotations

# (prefijo_de_senal, explicacion en texto plano). El match usa el PREFIJO MAS LARGO que
# calce, no el orden de la lista — evita el mismo bug de coincidencia parcial encontrado en
# strategies/registry.py.resolve() (2026-07-11: alias corto "pro" capturaba "prop_swing...").
_SIGNAL_RULES: list[tuple[str, str]] = [
    ("init",
     "Primera asignacion del bot (INIT): siembra la cartera en el %BTC base."),
    ("manual_wallet_reconcile",
     "Reconciliacion de auditoria: adopta el balance actual tras un ajuste ejecutado fuera "
     "del journal; no representa una orden de la estrategia."),
    ("regime_bull_suppressed_bear_onset",
     "Regimen alcista detectado pero SUPRIMIDO por fase bear_onset (mitigacion Q4 2025, v2) "
     "-> no se aplica sesgo alcista."),
    ("regime_bull",
     "Regimen alcista (EMA50D>EMA200D, precio>EMA200D, ADX>umbral) -> sesgo a MAS BTC."),
    ("regime_bear",
     "Regimen bajista (EMA50D<EMA200D) -> sesgo a MENOS BTC."),
    ("halving_bear_onset",
     "Fase de halving bear_onset (inicio de caida post-halving) -> sesgo a MENOS BTC."),
    ("halving_post_halving",
     "Fase de halving post_halving (recompra temprana de ciclo) -> sesgo a MAS BTC."),
    ("halving_bull_peak",
     "Fase de halving bull_peak (pico de ciclo) -> sesgo a MAS BTC."),
    ("mvrv_",
     "MVRV de valoracion (experimental, use_mvrv=False en default) -> ajuste por sobrevaloracion."),
    ("rsi_ob_",
     "RSI diario en sobrecompra (experimental, use_rsi=False en default) -> sesgo a MENOS BTC."),
    ("rsi_os_",
     "RSI diario en sobreventa (experimental, use_rsi=False en default) -> sesgo a MAS BTC."),
    ("pi_cycle_top",
     "Senal Pi Cycle Top (experimental, use_pi_cycle=False en default) -> sesgo a MENOS BTC."),
    ("vix_extreme_",
     "VIX en panico extremo (experimental, use_vix=False en default) -> ajuste defensivo."),
    ("vix_panic_",
     "VIX en panico moderado (experimental, use_vix=False en default) -> ajuste oportunista."),
    ("macd4h_bull",
     "MACD 4H alcista (experimental, use_macd_4h=False en default) -> sesgo a MAS BTC."),
    ("macd4h_bear",
     "MACD 4H bajista (experimental, use_macd_4h=False en default) -> sesgo a MENOS BTC."),
    ("funding_overlay_buy",
     "Overlay de funding v6 (fase accumulation): funding extremo negativo -> compra tactica."),
    ("funding_overlay_sell",
     "Overlay de funding v6 (fase accumulation): funding extremo positivo -> venta tactica."),
    ("funding_overlay_",
     "Overlay de funding v6 -> ajuste tactico por funding rate extremo."),
    ("funding_high_",
     "Funding rate alto (experimental, use_funding=False en default) -> sesgo a MENOS BTC."),
    ("funding_neg_",
     "Funding rate negativo (experimental, use_funding=False en default) -> sesgo a MAS BTC."),
    ("dxy_strong_",
     "DXY fuerte (experimental, use_dxy=False en default) -> sesgo a MENOS BTC."),
    ("dxy_weak_",
     "DXY debil (experimental, use_dxy=False en default) -> sesgo a MAS BTC."),
    ("bull_peak_ema50_cap_",
     "Cap de de-risk tardio de ciclo: perdio EMA50D en bull_peak -> topa el target."),
    ("bull_peak_cap_hold_",
     "Cap de de-risk tardio de ciclo sostenido (latch) -> mantiene el techo del target."),
]


def explain_signal(code: str) -> str:
    """Traduce un codigo de senal (tal como sale de _compute_target) a texto plano."""
    matches = [(len(prefix), text) for prefix, text in _SIGNAL_RULES
               if code == prefix or code.startswith(prefix)]
    if not matches:
        return (f"Senal no reconocida: '{code}' "
                f"(revisar strategies/swing_allocator.py._compute_target).")
    return max(matches, key=lambda m: m[0])[1]


def find_rebalance(
    rebalances: list[dict],
    strategy: str | None = None,
    date: str | None = None,
) -> dict | None:
    """Busca un rebalanceo en la lista ya leida de swing_rebalances.jsonl.

    strategy: filtra por strategy_name exacto (resolver el label v5/v6/legacy ANTES de llamar,
    ver tools/paper_bots.resolve_bot). date: filtra por prefijo YYYY-MM-DD del timestamp.
    Sin filtros -> el mas reciente de TODOS los bots. None si no hay match.
    """
    pool = rebalances
    if strategy:
        pool = [r for r in pool if r.get("strategy") == strategy]
    if date:
        pool = [r for r in pool if r.get("timestamp", "").startswith(date)]
    if not pool:
        return None
    return max(pool, key=lambda r: r.get("timestamp", ""))


def explain_rebalance(entry: dict) -> str:
    """Renderiza UN rebalanceo (linea de swing_rebalances.jsonl) en texto plano legible."""
    strategy = entry.get("strategy", "?")
    symbol = entry.get("symbol", "?")
    ts = entry.get("timestamp", "?")
    direction = entry.get("direction", "?")
    before = entry.get("btc_pct_before")
    target = entry.get("btc_pct_target")
    after = entry.get("btc_pct_after")
    price = entry.get("price")
    qty = entry.get("qty")
    portfolio = entry.get("portfolio_usdt")
    signals = entry.get("signals", [])

    lines = [
        f"Bot: {strategy} [{symbol}]",
        f"Timestamp: {ts}",
        f"Accion: {direction}",
    ]
    if before is not None and target is not None and after is not None:
        lines.append(
            f"Allocacion BTC: {before:.0%} -> objetivo {target:.0%} -> ejecutado {after:.0%}"
        )
    if price is not None:
        lines.append(f"Precio: ${price:,.2f}")
    if qty and direction in ("BUY", "SELL"):
        notional = qty * (price or 0)
        lines.append(f"Cantidad: {qty:.6f} BTC (~${notional:,.2f} notional)")
    if portfolio is not None:
        lines.append(f"Portfolio total: ${portfolio:,.2f}")

    lines.append("")
    lines.append("Causas (senales activas):")
    if signals:
        for s in signals:
            lines.append(f"  - {s}: {explain_signal(s)}")
    else:
        lines.append("  (ninguna registrada -> base_btc_pct sin ajustes)")

    lines.append("")
    lines.append(
        "Nota: cooldown y umbral de rebalanceo NO estan en este journal (gap conocido, "
        "ver T5.2 en docs/forward-test/research-lab-plan.md); fees/slippage no se registran "
        "por separado, solo el precio y la cantidad de la orden ejecutada."
    )
    return "\n".join(lines)
