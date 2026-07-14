"""Capa de datos multi-bot para el control remoto de Telegram (funciones puras).

Cada bot swing en paper puede tener su propia cartera aislada: la config lleva
`paper_portfolio_id` y el runtime escribe `data/runtime/paper_state_<id>.json`
(ver core/exchange.py). Los bots legacy sin ese campo siguen en `paper_state.json`.

Los rebalanceos de TODOS los bots se anexan al mismo `swing_rebalances.jsonl`, pero
cada linea lleva su campo `strategy` (= strategy_name del bot), asi que se separan por
filtro. Este modulo NO toca la logica de trading ni la DB: solo resuelve rutas, etiquetas
y filtros. Se mantiene aparte de telegram_remote.py para no pasar de las 800 lineas y para
poder testear el ruteo sin arrancar el servicio.
"""
from __future__ import annotations

import re
from pathlib import Path

# Espejo de OKXClient._safe_state_name (core/exchange.py). Duplicado a proposito: importar
# core.exchange arrastra el SDK de OKX; aqui solo necesitamos el mismo nombre de fichero.
_LABEL_RE = re.compile(r"_?(v\d+)_", re.I)


def safe_state_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in value.lower())
    return safe.strip("_-") or "default"


def is_operable_bot_name(name: str, symbol: str) -> bool:
    """True for runnable registrations; False for internal strategy-state rows."""
    suffix = "_" + str(symbol).upper().replace("-", "_").lower()
    return str(name).lower().endswith(suffix)


def paper_state_path(portfolio_id: str | None, runtime_dir: Path) -> Path:
    """Ruta de la cartera paper de un bot. Sin portfolio_id -> fichero legacy compartido."""
    if portfolio_id:
        return runtime_dir / f"paper_state_{safe_state_name(str(portfolio_id))}.json"
    return runtime_dir / "paper_state.json"


def bot_label(name: str, config: dict | None) -> str:
    """Etiqueta corta y estable para referirse al bot desde Telegram (v5, v6, legacy...).

    Prioridad: instance_id de la config > vN embebido en el strategy_name > 'legacy'.
    """
    inst = (config or {}).get("instance_id")
    if inst:
        return str(inst)
    m = _LABEL_RE.search(name or "")
    if m:
        return m.group(1).lower()
    return "legacy"


def resolve_bot(token: str, bots: list[dict]) -> dict | None:
    """Empareja un token del usuario (v6, legacy, o parte del strategy_name) con un bot.

    Exacto por etiqueta primero; si no, subcadena del strategy_name. None si no hay match
    claro o si es ambiguo por subcadena (>1 candidato)."""
    t = (token or "").strip().lower().lstrip("/")
    if not t:
        return None
    for b in bots:
        if b["label"].lower() == t:
            return b
    subs = [b for b in bots if t in b["name"].lower()]
    return subs[0] if len(subs) == 1 else None


def filter_rebalances(rebalances: list[dict], strategy_name: str | None) -> list[dict]:
    """Rebalanceos de UN bot. strategy_name None -> todos (comportamiento legacy)."""
    if strategy_name is None:
        return list(rebalances)
    return [r for r in rebalances if r.get("strategy") == strategy_name]
