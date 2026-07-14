"""Formateo de vistas para el control remoto de Telegram (funciones puras, HTML).

Separado de telegram_remote.py (orquestacion: red, subprocesos, DB, loop) para no pasar
del limite de 800 lineas por fichero y poder testear el render sin arrancar el servicio.
Nada de red ni IO aqui — solo dict/list -> str con parse_mode=HTML.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tools.paper_bots import bot_label
from tools.status_snapshot import MADRID, format_iso_madrid

LIVENESS_MAX_AGE_MIN = 10   # last_run mas viejo que esto con bot activo = proceso caido
PARITY_TARGET_DAYS = 30     # criterio de cierre F15

_DIR_ICON = {"BUY": "\U0001F7E2", "SELL": "\U0001F534", "INIT": "⚪"}  # verde/rojo/blanco


def _esc(s) -> str:
    """Escapa texto dinamico para parse_mode=HTML de Telegram."""
    return html.escape(str(s), quote=False)


def _next_4h_eval(now: datetime) -> tuple[datetime, int]:
    """Proximo cierre de bloque 4H UTC (00/04/08/12/16/20) y minutos restantes."""
    base = now.replace(minute=0, second=0, microsecond=0)
    nxt = base + timedelta(hours=4 - base.hour % 4)
    return nxt, int((nxt - now).total_seconds() // 60)


def _bot_status_icon(r, now: datetime) -> tuple[str, str]:
    if not r.is_active:
        return "⏸", "PAUSADO"
    if r.last_run is None:
        return "\U0001F7E1", "ACTIVO (sin tick aun)"
    last = r.last_run if r.last_run.tzinfo else r.last_run.replace(tzinfo=timezone.utc)
    age_min = (now - last).total_seconds() / 60
    if age_min <= LIVENESS_MAX_AGE_MIN:
        return "\U0001F7E2", f"VIVO (ultimo tick hace {age_min:.0f} min)"
    return "\U0001F534", f"ACTIVO PERO SIN TICK HACE {age_min:.0f} MIN — revisar proceso!"


def _bot_row(bot: dict):
    """Adaptador dict -> objeto que entienden format_status/heartbeat (r.strategy_name...)."""
    from types import SimpleNamespace
    return SimpleNamespace(strategy_name=bot["name"], symbol=bot["symbol"],
                           is_active=bot["is_active"], last_run=bot["last_run"])


def _perf_ratio(balances: dict, rebalances: list[dict], price: Decimal | None):
    """(total_usd, bot/B&H) desde el INIT. (total, None) o (None, None) si faltan datos."""
    if price is None or not rebalances:
        return None, None
    btc = balances.get("BTC", Decimal("0"))
    usdt = balances.get("USDT", Decimal("0"))
    total = btc * price + usdt
    init = rebalances[0]
    ip = Decimal(str(init.get("portfolio_usdt", 0)))
    ipr = Decimal(str(init.get("price", 0)))
    if ip > 0 and ipr > 0 and total > 0:
        return total, float(total / ip) / float(price / ipr)
    return total, None


def format_status_summary(snaps: list[dict], price: Decimal | None, now: datetime) -> str:
    """Resumen de TODOS los bots swing (una linea por bot). /status sin argumento."""
    lines = [f"\U0001F4CA <b>SWING — PAPER</b> ({len(snaps)} bot(s))"]
    if not snaps:
        lines.append("\nSin bots swing configurados "
                     "(python tools/swing_paper_setup.py --include-v5 --enable).")
        return "\n".join(lines)
    if price is not None:
        lines.append(f"BTC = ${price:,.0f}")
    for s in snaps:
        icon, _ = _bot_status_icon(_bot_row(s), now)
        total, ratio = _perf_ratio(s["balances"], s["rebalances"], price)
        btc = s["balances"].get("BTC", Decimal("0"))
        usdt = s["balances"].get("USDT", Decimal("0"))
        is_demo = s.get("execution") == "okx_demo"
        quote = s.get("execution_quote") or "USDT"
        parts = [f"{icon} <b>{_esc(s['label'])}</b>"]
        if total is not None and price is not None:
            pct = (btc * price / total * 100) if total > 0 else Decimal("0")
            parts.append(f"${total:,.0f} ({pct:.0f}% BTC)")
            if is_demo:
                parts.append("valoracion hibrida")
            elif ratio is not None:
                parts.append(f"bot/B&amp;H {ratio:.3f}")
        else:
            parts.append(f"{btc:.4f} BTC + {usdt:,.0f} {_esc(quote)}")
        parts.append(f"{len(s['rebalances'])} reb")
        lines.append(" · ".join(parts))
    if any(s.get("execution") == "okx_demo" for s in snaps):
        lines.append("<i>Demo: USDC real; valoracion con spot real, no usar como PnL.</i>")
    lines.append("")
    lines.append("Detalle: /status &lt;bot&gt; · /report &lt;bot&gt; · /equity &lt;bot&gt;")
    return "\n".join(lines)


def format_status(rows, balances: dict, price: Decimal | None,
                  rebalances: list[dict], now: datetime,
                  title: str = "SWING ALLOCATOR — PAPER",
                  quote_currency: str = "USDT",
                  performance_comparable: bool = True) -> str:
    lines = [f"\U0001F4CA <b>{_esc(title)}</b>", ""]
    if not rows:
        lines.append("Sin bots swing configurados (usa: python main.py bot enable ...)")
        return "\n".join(lines)

    for r in rows:
        icon, estado = _bot_status_icon(r, now)
        lines.append(f"{icon} <b>{_esc(r.strategy_name)}</b> [{_esc(r.symbol)}]: {estado}")

    btc = balances.get("BTC", Decimal("0"))
    usdt = balances.get("USDT", Decimal("0"))
    lines.append("")
    if price is not None:
        total = btc * price + usdt
        pct = (btc * price / total * 100) if total > 0 else Decimal("0")
        lines.append(f"\U0001F4B0 <b>Portfolio: ${total:,.2f}</b> ({pct:.1f}% en BTC)")
        lines.append(
            f"{btc:.6f} BTC (${btc * price:,.0f}) + "
            f"{usdt:,.2f} {_esc(quote_currency)}"
        )
        lines.append(f"BTC = ${price:,.0f}")
    else:
        lines.append(
            f"\U0001F4B0 Balance: {btc:.6f} BTC + "
            f"{usdt:.2f} {_esc(quote_currency)}"
        )
        lines.append("(precio BTC no disponible ahora mismo)")

    # Rendimiento desde el INIT: retorno del bot vs B&H BTC (la metrica ancla del Swing)
    if rebalances and price is not None and performance_comparable:
        init = rebalances[0]
        init_port = Decimal(str(init.get("portfolio_usdt", 0)))
        init_price = Decimal(str(init.get("price", 0)))
        if init_port > 0 and init_price > 0 and total > 0:
            bot_ret = (total / init_port - 1) * 100
            bnh_ret = (price / init_price - 1) * 100
            ratio = float(total / init_port) / float(price / init_price)
            days = max(0, (now - datetime.fromisoformat(init["timestamp"])).days) \
                if "timestamp" in init else 0
            lines.append("")
            lines.append(f"\U0001F4C8 <b>Rendimiento</b> ({days} dias, {len(rebalances)} rebalanceos)")
            lines.append(f"Bot {bot_ret:+.2f}% | B&amp;H BTC {bnh_ret:+.2f}% | bot/B&amp;H {ratio:.3f}")
    elif rebalances and not performance_comparable:
        lines.append("")
        lines.append("⚠️ <b>Rendimiento Demo no comparable</b>")
        lines.append(
            "Los fills Demo divergen del spot usado para valorar. El total es una "
            "valoracion hibrida, no PnL real."
        )

    if rebalances and price is not None and total > 0:
        actual_pct = float(btc * price / total)
        journal_pct = float(rebalances[-1].get("btc_pct_after", actual_pct))
        if abs(actual_pct - journal_pct) > 0.15:
            lines.append("")
            lines.append("⚠️ <b>Journal y cartera no coinciden</b>")
            lines.append(
                f"Ultimo evento: {journal_pct:.0%} BTC · cartera actual: {actual_pct:.0%}. "
                "Hay un ajuste fuera del journal."
            )

    if rebalances:
        rb = rebalances[-1]
        icon = _DIR_ICON.get(rb.get("direction", ""), "\U0001F501")
        lines.append("")
        lines.append("\U0001F501 <b>Ultimo rebalanceo</b>")
        lines.append(
            f"{icon} {format_iso_madrid(rb.get('timestamp'))} {rb.get('direction', '?')} "
            f"{rb.get('btc_pct_before', 0):.0%} → {rb.get('btc_pct_after', 0):.0%} "
            f"@ ${rb.get('price', 0):,.0f}"
        )
        if rb.get("signals"):
            lines.append(f"senales: {_esc(', '.join(rb['signals']))}")
    else:
        lines.append("")
        lines.append("Sin rebalanceos registrados aun.")

    nxt, mins = _next_4h_eval(now)
    lines.append("")
    local_nxt = nxt.astimezone(MADRID)
    lines.append(
        f"⏱ Proxima evaluacion 4H: {local_nxt:%H:%M} Europe/Madrid "
        f"(en {mins // 60}h {mins % 60:02d}m)"
    )
    return "\n".join(lines)


def format_report(rebalances: list[dict], n: int = 10, label: str | None = None) -> str:
    tag = f" [{label}]" if label else ""
    if not rebalances:
        return f"Sin rebalanceos registrados aun{tag}."
    total = len(rebalances)
    first_ts = rebalances[0].get("timestamp", "?")[:10]
    body = []
    for rb in rebalances[-n:]:
        icon = _DIR_ICON.get(rb.get("direction", ""), "\U0001F501")
        body.append(_esc(
            f"{icon} {format_iso_madrid(rb.get('timestamp'))} {rb.get('direction', '?'):4} "
            f"{rb.get('btc_pct_before', 0):.0%}→{rb.get('btc_pct_after', 0):.0%} "
            f"@ ${rb.get('price', 0):,.0f} | ${rb.get('portfolio_usdt', 0):,.0f} "
            f"| {','.join(rb.get('signals', []))}"
        ))
    lines = [f"\U0001F4D2 <b>REPORT{_esc(tag)}</b> — {total} rebalanceo(s) desde {first_ts}", ""]
    lines.append("<pre>" + "\n".join(body) + "</pre>")
    if total > n:
        lines.append(f"... ({total - n} anteriores omitidos; /report {total} para todos)")
    return "\n".join(lines)


_ANOMALY_ICON = {"CRITICAL": "\U0001F6A8", "HIGH": "\U0001F534",
                 "MEDIUM": "\U0001F7E1", "LOW": "\U000026AA"}


def format_anomalies(alerts: list) -> str:
    """Renderiza alertas de tools.anomaly_check.check_anomalies (plan T13.1) para /audit.

    No importa tools.anomaly_check (mismo criterio que el resto del modulo: solo HTML puro,
    sin dependencias de deteccion) — los objetos Alert solo se leen por atributo."""
    if not alerts:
        return "\U0001F7E2 <b>AUDITORIA</b>\nSin anomalias detectadas."
    lines = [f"\U0001F50E <b>AUDITORIA</b> — {len(alerts)} hallazgo(s)", ""]
    for a in alerts:
        icon = _ANOMALY_ICON.get(a.severity, "\U000026AA")
        tag = f" [{_esc(a.bot)}]" if a.bot else ""
        lines.append(f"{icon} <b>{_esc(a.severity)}</b>{tag} {_esc(a.code)}")
        lines.append(f"   {_esc(a.message)}")
        lines.append(f"   → {_esc(a.action)}")
    return "\n".join(lines)


def format_rebalance_alert(rb: dict) -> str:
    icon = _DIR_ICON.get(rb.get("direction", ""), "\U0001F501")
    tag = f" [{bot_label(rb['strategy'], None)}]" if rb.get("strategy") else ""
    lines = [
        f"{icon} <b>REBALANCEO{_esc(tag)}: {_esc(rb.get('direction', '?'))} "
        f"{rb.get('btc_pct_before', 0):.0%} → {rb.get('btc_pct_after', 0):.0%}</b>",
        f"{rb.get('timestamp', '?')[:16]} @ ${rb.get('price', 0):,.0f}",
        f"\U0001F4B0 Portfolio: ${rb.get('portfolio_usdt', 0):,.0f}",
    ]
    if rb.get("signals"):
        lines.append(f"senales: {_esc(', '.join(rb['signals']))}")
    return "\n".join(lines)


def parse_daily_checks(text: str) -> list[dict]:
    """Bloques del daily_checks.log -> [{ts, parity(bool|None), target}]."""
    blocks: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("===== daily_checks"):
            cur = {"ts": line.split()[2] if len(line.split()) > 2 else "?",
                   "parity": None, "target": None}
            blocks.append(cur)
        elif cur is not None:
            if line.startswith("live_target,"):
                cur["target"] = line.split(",", 1)[1].strip()
            elif line.strip() == "PARITY_OK":
                cur["parity"] = True
            elif "PARITY_FAIL" in line:
                cur["parity"] = False
    return blocks


def parity_streak(blocks: list[dict]) -> int:
    streak = 0
    for b in reversed(blocks):
        if b["parity"] is True:
            streak += 1
        else:
            break
    return streak


# Cron corre 1x/dia (12:10 UTC); 26h de margen antes de considerar el check "viejo".
# Mismo umbral que tools.anomaly_check.DAILY_CHECK_STALE_MIN — no importar cross-modulo solo
# por una constante (tg_views es HTML puro, anomaly_check es deteccion; se mantienen separados).
PARITY_STALE_MIN = 26 * 60


def format_parity(blocks: list[dict], now: datetime | None = None) -> str:
    if not blocks:
        return ("\U0001F50D <b>PARIDAD F15</b>\n"
                "Sin checks aun — el cron corre a las 12:10 UTC.")
    last = blocks[-1]
    if last["parity"] is True:
        icon, verdict = "\U0001F7E2", "OK"
    elif last["parity"] is False:
        icon, verdict = "\U0001F534", "FAIL — pausa e investiga (bug por definicion)"
    else:
        icon, verdict = "\U0001F7E1", "sin resultado (revisar log)"
    lines = [
        "\U0001F50D <b>PARIDAD F15</b>",
        f"{icon} Ultimo check {_esc(format_iso_madrid(last['ts']))}: {verdict}",
    ]
    # Bug real 2026-07-11: el cron perdio +x 5 dias y esto seguia mostrando "OK" en verde
    # porque antes solo miraba el ULTIMO resultado, nunca su antiguedad.
    if now is not None:
        try:
            ts = datetime.fromisoformat(last["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_min = (now - ts).total_seconds() / 60
            if age_min > PARITY_STALE_MIN:
                lines.append(
                    f"\U0001F534 <b>VIEJO: hace {age_min / 60:.1f}h</b> "
                    f"(esperado &lt;{PARITY_STALE_MIN / 60:.0f}h) — el cron probablemente "
                    f"no esta corriendo. Revisar crontab y permisos de daily_checks.sh."
                )
        except (KeyError, ValueError, TypeError):
            pass
    if last["target"]:
        lines.append(f"Target: {_esc(last['target'])}")
    lines.append(f"Racha: <b>{parity_streak(blocks)}/{PARITY_TARGET_DAYS}</b> dias OK")
    return "\n".join(lines)


def format_heartbeat_multi(snaps: list[dict], price: Decimal | None,
                           blocks: list[dict], now: datetime) -> str:
    """Heartbeat diario para N carteras: un segmento por bot + racha de paridad."""
    if not snaps:
        return "\U0001F493 sin bots swing configurados"
    segs = []
    for s in snaps:
        icon, _ = _bot_status_icon(_bot_row(s), now)
        total, ratio = _perf_ratio(s["balances"], s["rebalances"], price)
        seg = f"{icon}{_esc(s['label'])}"
        if total is not None:
            seg += f" ${total:,.0f}"
            if s.get("execution") == "okx_demo":
                seg += " (hibrido)"
            elif ratio is not None:
                seg += f" ({ratio:.3f})"
        segs.append(seg)
    return ("\U0001F493 " + " · ".join(segs)
            + f" | parity {parity_streak(blocks)}/{PARITY_TARGET_DAYS}")
