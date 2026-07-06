"""Capa de datos pura para observabilidad del paper forward-test (plan T4.2).

Fuente unica de verdad para "que estan haciendo los bots en paper AHORA", leida de la
persistencia que YA existe (DB SQLite + data/runtime/*), sin tocar la logica de trading:

  - BotState (core.database)        -> que bots hay, activos, ultimo tick
  - data/runtime/paper_state_<id>.json -> cartera aislada de cada bot (balances)
  - data/runtime/swing_rebalances.jsonl -> historial de rebalanceos (una linea por evento)
  - OKX public ticker               -> precio spot para valorar la cartera

La consumen: el control center (cli/paper_cmds.py), el chequeo de anomalias
(tools/anomaly_check.py) y el forward-report (tools/forward_report.py). Todo READ-ONLY.

Reutiliza los primitivos de tools/paper_bots.py (bot_label, paper_state_path,
filter_rebalances). NOTA DRY: tools/telegram_remote.py tiene lectores equivalentes
(discover_bots/bot_snapshots/read_paper_balances/read_rebalances/fetch_price) embebidos en
el servicio de larga duracion. No se refactoriza ese servicio durante el forward-test (evitar
desestabilizar el proceso desplegado); consolidar aqui queda como limpieza parqueada
(REFACTOR_BACKLOG). Este modulo es el hogar canonico de estas funciones de ahora en adelante.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "data" / "runtime"
REBALANCES = RUNTIME / "swing_rebalances.jsonl"
LEGACY_PAPER_STATE = RUNTIME / "paper_state.json"

# Espejo de tg_views.LIVENESS_MAX_AGE_MIN: bot activo sin tick mas viejo que esto = proceso caido.
LIVENESS_MAX_AGE_MIN = 10

# Nombre de la fila de estado interno del Swing en BotState — NO es un bot operable.
_STATE_ROW_NAME = "swing_allocator"


# ---------------------------------------------------------------------------
# Lectores de runtime (puros; toleran archivos ausentes en la maquina de dev)
# ---------------------------------------------------------------------------

def read_paper_balances(path: Path) -> dict[str, Decimal]:
    """Balances de una cartera paper. Dict vacio si no existe el fichero."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: Decimal(str(v)) for k, v in raw.get("balances", {}).items()}


def read_rebalances(path: Path = REBALANCES) -> list[dict]:
    """Todas las lineas del JSONL de rebalanceos (de TODOS los bots). [] si no existe."""
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def fetch_spot_price(symbol: str = "BTC-USDT", timeout: int = 10) -> Decimal | None:
    """Ticker publico OKX (sin credenciales). None ante cualquier fallo de red/API.

    User-Agent obligatorio: el Cloudflare de OKX devuelve 403 al UA por defecto de urllib
    (visto en el deploy GCP 2026-07-04). Mismo workaround que telegram_remote.fetch_price.
    NUNCA usar `requests` (CLAUDE.md) — urllib.request.
    """
    url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return Decimal(str(data["data"][0]["last"]))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Descubrimiento de bots desde la DB (dentro de la sesion, sin ORM colgante)
# ---------------------------------------------------------------------------

def discover_bots(session) -> list[dict]:
    """Datos planos de cada bot swing operable. Excluye la fila de estado interno.

    Cada dict: label, name, symbol, is_active, last_run (datetime|None), portfolio_id.
    Se adapta solo a 1/2/3 carteras sin hardcodear (mismo criterio que
    telegram_remote.swing_bot_rows + discover_bots)."""
    from tools.paper_bots import bot_label
    from core.database import BotState

    rows = (session.query(BotState)
            .filter(BotState.strategy_name.like("swing%"))
            .all())
    out = []
    for r in rows:
        if r.strategy_name == _STATE_ROW_NAME:
            continue
        cfg = r.get_config() or {}
        out.append({
            "label": bot_label(r.strategy_name, cfg),
            "name": r.strategy_name,
            "symbol": r.symbol,
            "is_active": r.is_active,
            "last_run": r.last_run,
            "portfolio_id": cfg.get("paper_portfolio_id"),
        })
    return out


# ---------------------------------------------------------------------------
# Metricas derivadas (numericas; el render vive en el consumidor)
# ---------------------------------------------------------------------------

def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def next_4h_eval(now: datetime) -> tuple[datetime, int]:
    """Proximo cierre de bloque 4H UTC (00/04/08/12/16/20) y minutos restantes.

    El Swing evalua en fronteras de bloque 4H; esta es la proxima ventana POSIBLE de
    rebalanceo (sujeta ademas al cooldown de min_days_between_rebalance)."""
    base = now.replace(minute=0, second=0, microsecond=0)
    nxt = base + timedelta(hours=4 - base.hour % 4)
    return nxt, int((nxt - now).total_seconds() // 60)


def perf_ratio(balances: dict, rebalances: list[dict],
               price: Decimal | None) -> tuple[Decimal | None, float | None]:
    """(equity_usd, bot/B&H) desde el INIT del bot. Espejo numerico de tg_views._perf_ratio.

    bot/B&H < 1.0 = el bot tiene menos valor que comprar y aguantar BTC desde el INIT.
    Devuelve (None, None) si faltan precio o rebalanceos; (equity, None) si falta el ancla INIT.
    """
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


def _staleness(is_active: bool, last_run: datetime | None,
               now: datetime) -> tuple[bool, float | None]:
    """(stale?, edad_en_min). stale = bot activo cuyo ultimo tick supera el umbral de liveness."""
    lr = _to_utc(last_run)
    if lr is None:
        return (is_active, None)  # activo sin tick aun = sospechoso
    age_min = (now - lr).total_seconds() / 60
    return (is_active and age_min > LIVENESS_MAX_AGE_MIN, age_min)


def build_snapshots(session, *, price: Decimal | None = None,
                    now: datetime | None = None,
                    rebalances_path: Path = REBALANCES) -> list[dict]:
    """Snapshot completo por bot: estado + cartera + rebalanceos + metricas derivadas.

    Una sola funcion pura (dado session/price/now) reutilizable por CLI, anomalias y report.
    NO escribe nada. Si `price` es None, las metricas monetarias quedan en None (se marca claro
    en el render). `now` inyectable para tests deterministas.
    """
    now = now or datetime.now(timezone.utc)
    bots = discover_bots(session)
    all_reb = read_rebalances(rebalances_path)

    snaps: list[dict] = []
    for b in bots:
        wallet = paper_state_path_for(b["portfolio_id"])
        balances = read_paper_balances(wallet)
        rebalances = filter_bot_rebalances(all_reb, b["name"])
        equity, ratio = perf_ratio(balances, rebalances, price)
        stale, age_min = _staleness(b["is_active"], b["last_run"], now)

        btc = balances.get("BTC", Decimal("0"))
        usdt = balances.get("USDT", Decimal("0"))
        btc_value = (btc * price) if price is not None else None
        btc_pct = (float(btc_value / equity * 100)
                   if (equity and btc_value is not None and equity > 0) else None)

        last_reb = rebalances[-1] if rebalances else None
        nxt_eval, mins_to_eval = next_4h_eval(now)

        snaps.append({
            **b,
            "wallet_path": str(wallet),
            "wallet_exists": wallet.exists(),
            "balances": balances,
            "btc": btc,
            "usdt": usdt,
            "btc_value": btc_value,
            "equity_usd": equity,
            "btc_pct": btc_pct,
            "bnh_ratio": ratio,
            "rebalances": rebalances,
            "n_rebalances": len(rebalances),
            "last_rebalance": last_reb,
            "last_run_age_min": age_min,
            "stale": stale,
            "next_eval_utc": nxt_eval,
            "mins_to_next_eval": mins_to_eval,
        })
    return snaps


# ---------------------------------------------------------------------------
# Envoltorios delgados sobre paper_bots (para no importar RUNTIME alli)
# ---------------------------------------------------------------------------

def paper_state_path_for(portfolio_id: str | None) -> Path:
    from tools.paper_bots import paper_state_path
    return paper_state_path(portfolio_id, RUNTIME)


def filter_bot_rebalances(all_reb: list[dict], strategy_name: str) -> list[dict]:
    from tools.paper_bots import filter_rebalances
    return filter_rebalances(all_reb, strategy_name)
