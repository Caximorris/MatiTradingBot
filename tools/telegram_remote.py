"""Control remoto del bot por Telegram (paper/live) — servicio de larga duracion.

Corre como proceso SEPARADO del bot de trading (ver deploy/matibot-telegram.service):
lee la misma DB SQLite, el portfolio paper y el JSONL de rebalanceos. No toca la
logica de trading — pausar/reanudar es el mismo flip de `is_active` que ya hace
`main.py bot enable/disable`, y el scheduler lo consulta en cada tick.

Comandos (solo responde al TELEGRAM_CHAT_ID configurado; ignora al resto):
    /status  — vivo/pausado, balances, % BTC, valor del portfolio, ultimo rebalanceo
    /report  — rebalanceos hasta la fecha (ultimos 10; /report 25 para mas)
    /pause   — pausa el Swing a distancia (is_active=False; el proceso sigue vivo)
    /resume  — reanuda (is_active=True)
    /help    — esta ayuda

Alertas automaticas: cada rebalanceo nuevo que aparezca en swing_rebalances.jsonl.

Requiere en .env: TELEGRAM_BOT_TOKEN (de @BotFather) y TELEGRAM_CHAT_ID (tu chat).
Sin red o con la API caida, reintenta indefinidamente — apto para systemd.
"""
from __future__ import annotations

import html
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger

from tools.tg_send import tg_api, tg_credentials, tg_send

PAPER_STATE = ROOT / "data" / "runtime" / "paper_state.json"
REBALANCES = ROOT / "data" / "runtime" / "swing_rebalances.jsonl"
STATE_ROW_NAME = "swing_allocator"   # fila de estado interno — NUNCA pausar/reanudar esta
LIVENESS_MAX_AGE_MIN = 10            # last_run mas viejo que esto con bot activo = proceso caido


# ---------------------------------------------------------------------------
# Datos (funciones puras / testeables)
# ---------------------------------------------------------------------------

def swing_bot_rows(session) -> list:
    from core.database import BotState
    return [
        r for r in session.query(BotState)
        .filter(BotState.strategy_name.like("swing%")).all()
        if r.strategy_name != STATE_ROW_NAME
    ]


def set_swing_active(session, active: bool) -> list[str]:
    rows = swing_bot_rows(session)
    for r in rows:
        r.is_active = active
    session.flush()
    return [r.strategy_name for r in rows]


def read_paper_balances(path: Path = PAPER_STATE) -> dict[str, Decimal]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: Decimal(str(v)) for k, v in raw.get("balances", {}).items()}


def read_rebalances(path: Path = REBALANCES) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def fetch_price(symbol: str = "BTC-USDT") -> Decimal | None:
    """Ticker publico OKX — sin credenciales."""
    url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return Decimal(str(data["data"][0]["last"]))
    except Exception as exc:
        logger.warning("fetch_price fallo: {}", exc)
        return None


_DIR_ICON = {"BUY": "\U0001F7E2", "SELL": "\U0001F534", "INIT": "⚪"}  # verde/rojo/blanco


def _esc(s) -> str:
    """Escapa texto dinamico para parse_mode=HTML de Telegram."""
    return html.escape(str(s), quote=False)


def _next_4h_eval(now: datetime) -> tuple[datetime, int]:
    """Proximo cierre de bloque 4H UTC (00/04/08/12/16/20) y minutos restantes."""
    base = now.replace(minute=0, second=0, microsecond=0)
    nxt = base + timedelta(hours=4 - base.hour % 4)
    return nxt, int((nxt - now).total_seconds() // 60)


def format_status(rows, balances: dict, price: Decimal | None,
                  rebalances: list[dict], now: datetime) -> str:
    lines = ["\U0001F4CA <b>SWING ALLOCATOR — PAPER</b>", ""]
    if not rows:
        lines.append("Sin bots swing configurados (usa: python main.py bot enable ...)")
        return "\n".join(lines)

    for r in rows:
        if not r.is_active:
            icon, estado = "⏸", "PAUSADO"
        elif r.last_run is None:
            icon, estado = "\U0001F7E1", "ACTIVO (sin tick aun)"
        else:
            last = r.last_run if r.last_run.tzinfo else r.last_run.replace(tzinfo=timezone.utc)
            age_min = (now - last).total_seconds() / 60
            if age_min <= LIVENESS_MAX_AGE_MIN:
                icon, estado = "\U0001F7E2", f"VIVO (ultimo tick hace {age_min:.0f} min)"
            else:
                icon, estado = "\U0001F534", f"ACTIVO PERO SIN TICK HACE {age_min:.0f} MIN — revisar proceso!"
        lines.append(f"{icon} <b>{_esc(r.strategy_name)}</b> [{_esc(r.symbol)}]: {estado}")

    btc = balances.get("BTC", Decimal("0"))
    usdt = balances.get("USDT", Decimal("0"))
    lines.append("")
    if price is not None:
        total = btc * price + usdt
        pct = (btc * price / total * 100) if total > 0 else Decimal("0")
        lines.append(f"\U0001F4B0 <b>Portfolio: ${total:,.2f}</b> ({pct:.1f}% en BTC)")
        lines.append(f"{btc:.6f} BTC (${btc * price:,.0f}) + {usdt:,.2f} USDT")
        lines.append(f"BTC = ${price:,.0f}")
    else:
        lines.append(f"\U0001F4B0 Balance: {btc:.6f} BTC + {usdt:.2f} USDT")
        lines.append("(precio BTC no disponible ahora mismo)")

    # Rendimiento desde el INIT: retorno del bot vs B&H BTC (la metrica ancla del Swing)
    if rebalances and price is not None:
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

    if rebalances:
        rb = rebalances[-1]
        icon = _DIR_ICON.get(rb.get("direction", ""), "\U0001F501")
        lines.append("")
        lines.append("\U0001F501 <b>Ultimo rebalanceo</b>")
        lines.append(
            f"{icon} {rb.get('timestamp', '?')[:16]} {rb.get('direction', '?')} "
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
    lines.append(f"⏱ Proxima evaluacion 4H: {nxt:%H:%M} UTC (en {mins // 60}h {mins % 60:02d}m)")
    return "\n".join(lines)


def format_report(rebalances: list[dict], n: int = 10) -> str:
    if not rebalances:
        return "Sin rebalanceos registrados aun."
    total = len(rebalances)
    first_ts = rebalances[0].get("timestamp", "?")[:10]
    body = []
    for rb in rebalances[-n:]:
        icon = _DIR_ICON.get(rb.get("direction", ""), "\U0001F501")
        body.append(_esc(
            f"{icon} {rb.get('timestamp', '?')[5:16]} {rb.get('direction', '?'):4} "
            f"{rb.get('btc_pct_before', 0):.0%}→{rb.get('btc_pct_after', 0):.0%} "
            f"@ ${rb.get('price', 0):,.0f} | ${rb.get('portfolio_usdt', 0):,.0f} "
            f"| {','.join(rb.get('signals', []))}"
        ))
    lines = [f"\U0001F4D2 <b>REPORT</b> — {total} rebalanceo(s) desde {first_ts}", ""]
    lines.append("<pre>" + "\n".join(body) + "</pre>")
    if total > n:
        lines.append(f"... ({total - n} anteriores omitidos; /report {total} para todos)")
    return "\n".join(lines)


def format_rebalance_alert(rb: dict) -> str:
    icon = _DIR_ICON.get(rb.get("direction", ""), "\U0001F501")
    lines = [
        f"{icon} <b>REBALANCEO: {_esc(rb.get('direction', '?'))} "
        f"{rb.get('btc_pct_before', 0):.0%} → {rb.get('btc_pct_after', 0):.0%}</b>",
        f"{rb.get('timestamp', '?')[:16]} @ ${rb.get('price', 0):,.0f}",
        f"\U0001F4B0 Portfolio: ${rb.get('portfolio_usdt', 0):,.0f}",
    ]
    if rb.get("signals"):
        lines.append(f"senales: {_esc(', '.join(rb['signals']))}")
    return "\n".join(lines)


HELP_TEXT = (
    "\U0001F916 <b>Comandos</b>\n"
    "/status — estado, balances, rendimiento vs B&amp;H\n"
    "/report [n] — ultimos n rebalanceos (10 por defecto)\n"
    "/pause — pausar el Swing (el proceso sigue; no decide)\n"
    "/resume — reanudar\n"
    "/help — esta ayuda"
)


# ---------------------------------------------------------------------------
# Despacho de comandos
# ---------------------------------------------------------------------------

def handle_command(text: str, get_session) -> str:
    parts = text.strip().split()
    if not parts:
        return HELP_TEXT
    cmd = parts[0].lower().split("@")[0]

    if cmd == "/status":
        with get_session() as s:
            rows = swing_bot_rows(s)
            return format_status(rows, read_paper_balances(), fetch_price(),
                                 read_rebalances(), datetime.now(timezone.utc))
    if cmd == "/report":
        n = 10
        if len(parts) > 1 and parts[1].isdigit():
            n = max(1, min(int(parts[1]), 100))
        return format_report(read_rebalances(), n)
    if cmd == "/pause":
        with get_session() as s:
            names = set_swing_active(s, False)
        return f"⏸ PAUSADO: {_esc(', '.join(names)) or 'nada que pausar'}"
    if cmd == "/resume":
        with get_session() as s:
            names = set_swing_active(s, True)
        return f"▶️ REANUDADO: {_esc(', '.join(names)) or 'nada que reanudar'}"
    return HELP_TEXT


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def main() -> None:
    token, chat_id = tg_credentials()
    if not token or not chat_id:
        raise SystemExit("Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env")

    from core.database import get_session, init_db
    init_db()

    # Saltar el backlog de updates: un /resume viejo re-ejecutado tras un restart
    # seria una orden fantasma.
    offset = None
    try:
        resp = tg_api("getUpdates", {"timeout": 0})
        if resp.get("result"):
            offset = resp["result"][-1]["update_id"] + 1
    except Exception as exc:
        logger.warning("No se pudo limpiar backlog de updates: {}", exc)

    seen_rebalances = len(read_rebalances())
    tg_send("\U0001F916 Control remoto conectado. /help para comandos.")
    logger.info("telegram_remote arrancado (rebalanceos ya registrados: {})", seen_rebalances)

    while True:
        # 1) Alertas: rebalanceos nuevos en el JSONL
        try:
            rebalances = read_rebalances()
            for rb in rebalances[seen_rebalances:]:
                tg_send(format_rebalance_alert(rb), parse_mode="HTML")
            seen_rebalances = len(rebalances)
        except Exception as exc:
            logger.warning("Chequeo de rebalanceos fallo: {}", exc)

        # 2) Comandos (long-poll 50s: sin puertos abiertos, solo trafico saliente)
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset
            resp = tg_api("getUpdates", params, timeout=60)
        except Exception as exc:
            logger.warning("getUpdates fallo (reintento en 10s): {}", exc)
            time.sleep(10)
            continue

        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message") or {}
            text = msg.get("text", "")
            sender = str((msg.get("chat") or {}).get("id", ""))
            if sender != chat_id:
                logger.warning("Mensaje ignorado de chat no autorizado: {}", sender)
                continue
            if not text:
                continue
            try:
                reply = handle_command(text, get_session)
            except Exception as exc:
                logger.exception("Comando '{}' fallo", text)
                reply = f"⚠️ Error ejecutando '{_esc(text)}': {_esc(exc)}"
            tg_send(reply, parse_mode="HTML")


if __name__ == "__main__":
    main()
