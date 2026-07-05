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
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger

from tools.tg_send import tg_api, tg_credentials, tg_send, tg_send_document, tg_send_photo

PAPER_STATE = ROOT / "data" / "runtime" / "paper_state.json"
REBALANCES = ROOT / "data" / "runtime" / "swing_rebalances.jsonl"
DAILY_CHECKS_LOG = ROOT / "data" / "runtime" / "daily_checks.log"
TG_STATE = ROOT / "data" / "runtime" / "tg_state.json"   # heartbeat/backup/watchdog persistido
TRADING_DB = ROOT / "trading.db"
STATE_ROW_NAME = "swing_allocator"   # fila de estado interno — NUNCA pausar/reanudar esta
LIVENESS_MAX_AGE_MIN = 10            # last_run mas viejo que esto con bot activo = proceso caido
UNIT_BOT = "matibot"
UNIT_TG = "matibot-telegram"
HEARTBEAT_HOUR_UTC = 8               # 1 mensaje/dia: el silencio deja de ser ambiguo
BACKUP_EVERY_DAYS = 7                # backup automatico semanal al chat
PARITY_TARGET_DAYS = 30              # criterio de cierre F15


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


def prop_bot_rows(session) -> list:
    from core.database import BotState
    return [
        r for r in session.query(BotState)
        .filter(BotState.strategy_name.like("prop_swing%")).all()
        if r.strategy_name != "prop_swing"
    ]


def set_swing_active(session, active: bool) -> list[str]:
    rows = swing_bot_rows(session)
    for r in rows:
        r.is_active = active
    session.flush()
    return [r.strategy_name for r in rows]


def set_prop_active(session, active: bool) -> list[str]:
    rows = prop_bot_rows(session)
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
    """Ticker publico OKX — sin credenciales.

    User-Agent obligatorio: el Cloudflare de OKX devuelve 403 al UA por defecto
    de urllib (visto en el deploy GCP 2026-07-04); curl y aiohttp pasan.
    """
    url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
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


# ---------------------------------------------------------------------------
# Sistema: subprocesos, journal, salud
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 30, use_sudo: bool = False) -> tuple[int, str]:
    """Ejecuta un comando y devuelve (rc, salida). sudo -n = nunca pide password
    (en GCP el usuario tiene NOPASSWD via google-sudoers)."""
    if use_sudo:
        cmd = ["sudo", "-n"] + cmd
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _journal(unit: str, extra: list[str], timeout: int = 30) -> str:
    """journalctl con fallback a sudo (el usuario puede no estar en el grupo adm)."""
    base = ["journalctl", "-u", unit, "--no-pager", *extra]
    rc, out = _run(base, timeout)
    if rc != 0:
        _, out = _run(base, timeout, use_sudo=True)
    return out


def format_health() -> str:
    lines = ["\U0001FA7A <b>SALUD</b>", ""]
    for unit in (UNIT_BOT, UNIT_TG):
        _, state = _run(["systemctl", "is-active", unit])
        icon = "\U0001F7E2" if state == "active" else "\U0001F534"
        lines.append(f"{icon} {unit}: {_esc(state or '?')}")
    try:
        mem = {}
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, v = ln.split(":", 1)
            mem[k] = int(v.strip().split()[0])
        ram = 100 * (1 - mem["MemAvailable"] / mem["MemTotal"])
        swap = 100 * (1 - mem["SwapFree"] / mem["SwapTotal"]) if mem.get("SwapTotal") else 0.0
        lines.append(f"RAM {ram:.0f}% | swap {swap:.0f}%")
    except Exception:
        lines.append("RAM: n/d (no-Linux)")
    du = shutil.disk_usage(ROOT)
    lines.append(f"Disco {du.used / du.total * 100:.0f}% ({du.free / 2**30:.1f} GB libres)")
    try:
        lines.append(f"Load 1m: {Path('/proc/loadavg').read_text().split()[0]}")
    except Exception:
        pass
    out = _journal(UNIT_BOT, ["--since", "24 hours ago", "-o", "cat"], timeout=60)
    n_err = len([ln for ln in out.splitlines()
                 if re.search(r"error|exception|traceback", ln, re.I)])
    icon = "\U0001F7E2" if n_err == 0 else "\U0001F534"
    lines.append(f"{icon} Errores en journal 24h: {n_err}")
    return "\n".join(lines)


def cmd_logs(n: int) -> str:
    out = _journal(UNIT_BOT, ["-n", str(n), "-o", "short-iso"])
    if not out:
        return "Journal vacio o inaccesible."
    return f"\U0001F4DC <b>LOGS matibot</b> (ultimas {n})\n<pre>{_esc(out)[-3500:]}</pre>"


# ---------------------------------------------------------------------------
# Paridad F15 y senales
# ---------------------------------------------------------------------------

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


def format_parity(blocks: list[dict]) -> str:
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
        f"{icon} Ultimo check {_esc(last['ts'])}: {verdict}",
    ]
    if last["target"]:
        lines.append(f"Target: {_esc(last['target'])}")
    lines.append(f"Racha: <b>{parity_streak(blocks)}/{PARITY_TARGET_DAYS}</b> dias OK")
    return "\n".join(lines)


def cmd_signals() -> str:
    tg_send("⏳ Calculando senales (descarga 6000 velas, ~1 min)...")
    rc, out = _run([sys.executable, str(ROOT / "tools" / "swing_parity_check.py")],
                   timeout=300)
    kv = dict(ln.split(",", 1) for ln in out.splitlines() if "," in ln)
    if "live_target" not in kv:
        return f"⚠️ swing_parity_check fallo (rc={rc}):\n<pre>{_esc(out[-1000:])}</pre>"
    icon = "\U0001F7E2" if rc == 0 else "\U0001F534"
    signals = kv.get("live_signals", "").replace(";", ", ") or "ninguna"
    lines = [
        "\U0001F9ED <b>SENALES ACTUALES</b>",
        f"Target BTC: <b>{_esc(kv['live_target'])}</b>",
        f"Senales: {_esc(signals)}",
        f"Dato: {_esc(kv.get('timestamp', '?')[:16])} UTC",
        f"{icon} Paridad live/backtest: {'OK' if rc == 0 else 'FAIL'}",
    ]
    price = fetch_price()
    if price is not None:
        lines.append(f"BTC = ${price:,.0f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graficos y backup
# ---------------------------------------------------------------------------

def _parse_days(parts: list[str], default: int = 30) -> int:
    if len(parts) > 1 and parts[1].isdigit():
        return max(2, min(int(parts[1]), 60))
    return default


def cmd_equity(days: int) -> str | None:
    from tools.tg_charts import build_equity_series, fetch_candles, render_equity_png
    rebalances = read_rebalances()
    if not rebalances:
        return "Sin rebalanceos aun — no hay equity que dibujar."
    tg_send("⏳ Generando grafico de equity...")
    candles = fetch_candles(days=days)
    series = build_equity_series(rebalances, candles)
    if not series["ts"]:
        return "Datos insuficientes para el grafico (velas o INIT no cubiertos)."
    png = render_equity_png(series, days)
    bot0, bot1 = series["bot"][0], series["bot"][-1]
    bnh0, bnh1 = series["bnh"][0], series["bnh"][-1]
    ratio = (bot1 / bot0) / (bnh1 / bnh0) if bot0 and bnh0 and bnh1 else 0
    caption = (f"Bot ${bot1:,.0f} ({(bot1 / bot0 - 1) * 100:+.2f}%) | "
               f"B&H ${bnh1:,.0f} ({(bnh1 / bnh0 - 1) * 100:+.2f}%) | "
               f"bot/B&H {ratio:.3f}")
    return None if tg_send_photo(png, caption) else "Fallo enviando el grafico."


def cmd_chart(days: int) -> str | None:
    from tools.tg_charts import fetch_candles, render_price_png
    tg_send("⏳ Generando grafico de precio...")
    candles = fetch_candles(days=days)
    if not candles:
        return "OKX no devolvio velas."
    png = render_price_png(candles, read_rebalances(), days)
    caption = f"BTC ${candles[-1][1]:,.0f} | {days}d 1H | rebalanceos marcados"
    return None if tg_send_photo(png, caption) else "Fallo enviando el grafico."


def cmd_backup() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    sent = []
    for p in (TRADING_DB, PAPER_STATE, REBALANCES, DAILY_CHECKS_LOG):
        if p.exists() and tg_send_document(f"{stamp}_{p.name}", p.read_bytes(),
                                           caption=f"backup {stamp} — {p.name}"):
            sent.append(p.name)
    if not sent:
        return "Nada que respaldar (o fallo el envio)."
    return f"\U0001F4E6 Backup enviado: {_esc(', '.join(sent))}"


# ---------------------------------------------------------------------------
# Operaciones remotas (/restart /update)
# ---------------------------------------------------------------------------

def cmd_restart() -> str:
    rc, out = _run(["systemctl", "restart", UNIT_BOT], use_sudo=True, timeout=60)
    if rc != 0:
        return f"⚠️ Fallo el restart:\n<pre>{_esc(out[-500:])}</pre>"
    return f"\U0001F504 {UNIT_BOT} reiniciado."


def cmd_update() -> str | None:
    rc, out = _run(["git", "pull", "--ff-only"], timeout=120)
    if rc != 0:
        return f"⚠️ git pull fallo:\n<pre>{_esc(out[-800:])}</pre>"
    if "Already up to date" in out or "Ya está actualizado" in out:
        return "\U0001F7E2 Sin cambios (repo al dia)."
    reply = (f"\U0001F4E5 <b>Actualizado</b>:\n<pre>{_esc(out[-800:])}</pre>\n"
             + cmd_restart())
    # Si cambio el propio control remoto, reiniciarse a si mismo (lo mata systemd
    # y vuelve con el codigo nuevo) — el mensaje sale ANTES del harakiri.
    if re.search(r"telegram_remote|tg_send|tg_charts", out):
        tg_send(reply + "\n\U0001F504 Reiniciando tambien el control remoto...",
                parse_mode="HTML")
        _run(["systemctl", "restart", UNIT_TG], use_sudo=True, timeout=60)
        return None
    return reply


# ---------------------------------------------------------------------------
# Heartbeat, watchdog y estado persistido del propio control remoto
# ---------------------------------------------------------------------------

def _load_tg_state() -> dict:
    try:
        return json.loads(TG_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_tg_state(state: dict) -> None:
    try:
        TG_STATE.parent.mkdir(parents=True, exist_ok=True)
        TG_STATE.write_text(json.dumps(state), encoding="utf-8")
    except Exception as exc:
        logger.warning("No se pudo persistir tg_state: {}", exc)


def format_heartbeat(rows, balances: dict, price: Decimal | None,
                     rebalances: list[dict], blocks: list[dict],
                     now: datetime) -> str:
    alive = any(
        r.is_active and r.last_run is not None
        and (now - (r.last_run if r.last_run.tzinfo else r.last_run.replace(tzinfo=timezone.utc))
             ).total_seconds() / 60 <= LIVENESS_MAX_AGE_MIN
        for r in rows
    )
    paused = bool(rows) and all(not r.is_active for r in rows)
    icon = "⏸" if paused else ("\U0001F7E2" if alive else "\U0001F534")
    state_txt = "pausado" if paused else ("vivo" if alive else "SIN TICK — revisar!")
    parts = [f"\U0001F493 {icon} {state_txt}"]
    btc = balances.get("BTC", Decimal("0"))
    usdt = balances.get("USDT", Decimal("0"))
    if price is not None:
        total = btc * price + usdt
        pct = (btc * price / total * 100) if total > 0 else Decimal("0")
        parts.append(f"${total:,.0f} ({pct:.0f}% BTC)")
        if rebalances:
            init = rebalances[0]
            ip, ipr = Decimal(str(init.get("portfolio_usdt", 0))), Decimal(str(init.get("price", 0)))
            if ip > 0 and ipr > 0 and total > 0:
                parts.append(f"bot/B&H {float(total / ip) / float(price / ipr):.3f}")
    parts.append(f"parity {parity_streak(blocks)}/{PARITY_TARGET_DAYS}")
    parts.append(f"{len(rebalances)} rebalanceos")
    return " · ".join(parts)


HELP_TEXT = (
    "\U0001F916 <b>Comandos</b>\n"
    "\n<b>Estado</b>\n"
    "/status — estado, balances, rendimiento vs B&amp;H\n"
    "/prop — estado Prop/CFT y ultimos eventos\n"
    "/prop_report [n] — ultimos eventos PropSwing\n"
    "/report [n] — ultimos n rebalanceos\n"
    "/signals — target y senales actuales (calculo live)\n"
    "/parity — paridad F15: ultimo check y racha /30\n"
    "\n<b>Graficos</b>\n"
    "/equity [dias] — equity del bot vs B&amp;H BTC (30 por defecto)\n"
    "/chart [dias] — precio BTC con rebalanceos marcados\n"
    "\n<b>VM y servicios</b>\n"
    "/health — servicios, RAM/disco, errores 24h\n"
    "/logs [n] — ultimas n lineas del journal (30 por defecto)\n"
    "/backup — enviar DB + estado como archivos\n"
    "/restart — reiniciar matibot\n"
    "/update — git pull + restart\n"
    "\n<b>Control</b>\n"
    "/pause — pausar el Swing (el proceso sigue; no decide)\n"
    "/resume — reanudar\n"
    "/prop_pause — pausar PropSwing\n"
    "/prop_resume — reanudar PropSwing\n"
    "\nAutomatico: alerta de rebalanceo, watchdog sin-tick, heartbeat diario "
    "08:00 UTC, backup semanal."
)

BOT_COMMANDS = [
    ("status", "Estado, balances y rendimiento"),
    ("prop", "Estado Prop/CFT"),
    ("prop_report", "Eventos PropSwing"),
    ("report", "Ultimos rebalanceos"),
    ("equity", "Grafico equity vs B&H"),
    ("chart", "Grafico precio + rebalanceos"),
    ("signals", "Target y senales actuales"),
    ("parity", "Paridad F15 y racha"),
    ("health", "Salud de VM y servicios"),
    ("logs", "Journal del bot"),
    ("backup", "Backup de DB y estado"),
    ("pause", "Pausar el Swing"),
    ("resume", "Reanudar el Swing"),
    ("prop_pause", "Pausar PropSwing"),
    ("prop_resume", "Reanudar PropSwing"),
    ("restart", "Reiniciar matibot"),
    ("update", "git pull + restart"),
    ("help", "Ayuda"),
]


# ---------------------------------------------------------------------------
# Despacho de comandos
# ---------------------------------------------------------------------------

def handle_command(text: str, get_session) -> str | None:
    """Devuelve la respuesta de texto, o None si el comando ya envio lo suyo
    (fotos, documentos, o el /update que se reinicia a si mismo)."""
    parts = text.strip().split()
    if not parts:
        return HELP_TEXT
    cmd = parts[0].lower().split("@")[0]

    if cmd == "/status":
        with get_session() as s:
            rows = swing_bot_rows(s)
            return format_status(rows, read_paper_balances(), fetch_price(),
                                 read_rebalances(), datetime.now(timezone.utc))
    if cmd == "/prop":
        from tools.prop_telegram import format_prop_status
        with get_session() as s:
            return format_prop_status(prop_bot_rows(s), LIVENESS_MAX_AGE_MIN)
    if cmd == "/prop_report":
        from tools.prop_telegram import format_prop_report
        n = 20
        if len(parts) > 1 and parts[1].isdigit():
            n = max(1, min(int(parts[1]), 100))
        return format_prop_report(n)
    if cmd == "/report":
        n = 10
        if len(parts) > 1 and parts[1].isdigit():
            n = max(1, min(int(parts[1]), 100))
        return format_report(read_rebalances(), n)
    if cmd == "/signals":
        return cmd_signals()
    if cmd == "/parity":
        text_log = DAILY_CHECKS_LOG.read_text(encoding="utf-8") if DAILY_CHECKS_LOG.exists() else ""
        return format_parity(parse_daily_checks(text_log))
    if cmd == "/equity":
        return cmd_equity(_parse_days(parts))
    if cmd == "/chart":
        return cmd_chart(_parse_days(parts))
    if cmd == "/health":
        return format_health()
    if cmd == "/logs":
        n = 30
        if len(parts) > 1 and parts[1].isdigit():
            n = max(5, min(int(parts[1]), 200))
        return cmd_logs(n)
    if cmd == "/backup":
        return cmd_backup()
    if cmd == "/restart":
        return cmd_restart()
    if cmd == "/update":
        return cmd_update()
    if cmd == "/pause":
        with get_session() as s:
            names = set_swing_active(s, False)
        return f"⏸ PAUSADO: {_esc(', '.join(names)) or 'nada que pausar'}"
    if cmd == "/resume":
        with get_session() as s:
            names = set_swing_active(s, True)
        return f"▶️ REANUDADO: {_esc(', '.join(names)) or 'nada que reanudar'}"
    if cmd == "/prop_pause":
        with get_session() as s:
            names = set_prop_active(s, False)
        return f"⏸ PROP PAUSADO: {_esc(', '.join(names)) or 'nada que pausar'}"
    if cmd == "/prop_resume":
        with get_session() as s:
            names = set_prop_active(s, True)
        return f"▶️ PROP REANUDADO: {_esc(', '.join(names)) or 'nada que reanudar'}"
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
    try:
        tg_api("setMyCommands", {"commands": json.dumps(
            [{"command": c, "description": d} for c, d in BOT_COMMANDS])})
    except Exception as exc:
        logger.warning("setMyCommands fallo: {}", exc)
    tg_send("\U0001F916 Control remoto conectado. /help para comandos.")
    logger.info("telegram_remote arrancado (rebalanceos ya registrados: {})", seen_rebalances)

    tg_state = _load_tg_state()

    while True:
        now = datetime.now(timezone.utc)

        # 1) Alertas: rebalanceos nuevos en el JSONL
        try:
            rebalances = read_rebalances()
            for rb in rebalances[seen_rebalances:]:
                tg_send(format_rebalance_alert(rb), parse_mode="HTML")
            seen_rebalances = len(rebalances)
        except Exception as exc:
            logger.warning("Chequeo de rebalanceos fallo: {}", exc)

        # 1b) Watchdog: bot activo pero sin tick -> alerta push (una vez por caida)
        try:
            with get_session() as s:
                rows = swing_bot_rows(s)
                stale = [
                    r.strategy_name for r in rows
                    if r.is_active and r.last_run is not None
                    and (now - (r.last_run if r.last_run.tzinfo
                                else r.last_run.replace(tzinfo=timezone.utc))
                         ).total_seconds() / 60 > LIVENESS_MAX_AGE_MIN
                ]
            if stale and not tg_state.get("watchdog_alerted"):
                tg_send(f"\U0001F534 WATCHDOG: sin tick hace >{LIVENESS_MAX_AGE_MIN} min "
                        f"en {', '.join(stale)}. Prueba /restart o revisa /logs.")
                tg_state["watchdog_alerted"] = True
                _save_tg_state(tg_state)
            elif not stale and tg_state.get("watchdog_alerted"):
                tg_send("\U0001F7E2 WATCHDOG: tick recuperado.")
                tg_state["watchdog_alerted"] = False
                _save_tg_state(tg_state)
        except Exception as exc:
            logger.warning("Watchdog fallo: {}", exc)

        # 1c) Heartbeat diario: 1 mensaje a partir de las HEARTBEAT_HOUR_UTC
        try:
            today = now.date().isoformat()
            if now.hour >= HEARTBEAT_HOUR_UTC and tg_state.get("last_heartbeat") != today:
                with get_session() as s:
                    rows = swing_bot_rows(s)
                    blocks = parse_daily_checks(
                        DAILY_CHECKS_LOG.read_text(encoding="utf-8")
                        if DAILY_CHECKS_LOG.exists() else "")
                    hb = format_heartbeat(rows, read_paper_balances(), fetch_price(),
                                          read_rebalances(), blocks, now)
                tg_send(hb, parse_mode="HTML")
                tg_state["last_heartbeat"] = today
                _save_tg_state(tg_state)
        except Exception as exc:
            logger.warning("Heartbeat fallo: {}", exc)

        # 1d) Backup automatico semanal
        try:
            last = tg_state.get("last_backup")
            due = (last is None
                   or (now.date() - datetime.fromisoformat(last).date()).days >= BACKUP_EVERY_DAYS)
            if due:
                tg_send(cmd_backup(), parse_mode="HTML")
                tg_state["last_backup"] = now.date().isoformat()
                _save_tg_state(tg_state)
        except Exception as exc:
            logger.warning("Backup automatico fallo: {}", exc)

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
            if reply:
                tg_send(reply, parse_mode="HTML")


if __name__ == "__main__":
    main()
