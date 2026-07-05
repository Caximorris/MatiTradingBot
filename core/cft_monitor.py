"""Operational monitor for Crypto Fund Trader style evaluations.

The monitor is intentionally separate from the alpha logic. It consumes the
current equity and optional trade events, then persists a small JSON status
file that can be inspected from Telegram, cron, or a VM shell.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path("data") / "runtime"
CFT_STATUS_PATH = RUNTIME_DIR / "prop_cft_status.json"
CFT_EVENTS_PATH = RUNTIME_DIR / "prop_cft_events.jsonl"


@dataclass(frozen=True)
class CFTMonitorConfig:
    account_size: float = 50_000.0
    phase: str = "p1"                  # p1 target=8%, p2 target=5%, funded target=none
    daily_dd_pct: float = 0.05
    max_loss_pct: float = 0.10
    min_trading_days: int = 5
    max_trade_loss_pct: float = 1.0    # CFT two-phase: no strict per-trade cap in our model
    warn_buffer_pct: float = 0.01      # alert when cushion to a hard rule is <= 1%
    halt_buffer_pct: float = 0.003     # block/flatten when cushion is <= 0.3%

    @property
    def profit_target_pct(self) -> float | None:
        if self.phase.lower() == "p1":
            return 0.08
        if self.phase.lower() == "p2":
            return 0.05
        return None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _date_key(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date().isoformat()


def load_status(path: Path = CFT_STATUS_PATH) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_status(status: dict[str, Any], path: Path = CFT_STATUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=True, indent=2), encoding="utf-8")


def append_event(event: dict[str, Any], path: Path = CFT_EVENTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")


def read_events(path: Path = CFT_EVENTS_PATH, limit: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:]


def new_status(
    *,
    strategy: str,
    symbol: str,
    ts: datetime,
    equity: float,
    cfg: CFTMonitorConfig,
) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "symbol": symbol,
        "phase": cfg.phase,
        "started_at": _iso(ts),
        "updated_at": _iso(ts),
        "start_equity": equity,
        "account_size": cfg.account_size,
        "current_day": _date_key(ts),
        "day_start_rel": 1.0,
        "day_peak_rel": 1.0,
        "trading_dates": [],
        "worst_trade_pct": 0.0,
        "status": "running",
        "last_rule_state": "running",
    }


def update_status(
    *,
    strategy: str,
    symbol: str,
    ts: datetime,
    equity: float,
    cfg: CFTMonitorConfig,
    trade_event: dict[str, Any] | None = None,
    status_path: Path = CFT_STATUS_PATH,
    events_path: Path = CFT_EVENTS_PATH,
) -> dict[str, Any]:
    """Update and persist the monitor.

    The account is normalized to the equity observed on the first update. This
    lets a $10k paper portfolio represent a $50k CFT account without changing
    exchange balances.
    """
    status = load_status(status_path)
    if (
        not status
        or status.get("strategy") != strategy
        or status.get("symbol") != symbol
        or status.get("phase") != cfg.phase
    ):
        status = new_status(strategy=strategy, symbol=symbol, ts=ts, equity=equity, cfg=cfg)

    start_equity = float(status.get("start_equity") or equity)
    if start_equity <= 0:
        start_equity = equity if equity > 0 else 1.0
        status["start_equity"] = start_equity
    rel = equity / start_equity

    day_key = _date_key(ts)
    if status.get("current_day") != day_key:
        status["current_day"] = day_key
        status["day_start_rel"] = rel
        status["day_peak_rel"] = rel
    else:
        status["day_peak_rel"] = max(float(status.get("day_peak_rel", rel)), rel)

    if trade_event is not None:
        kind = str(trade_event.get("kind", "event"))
        if kind in {"open", "tp1", "close"}:
            dates = list(status.get("trading_dates", []))
            if day_key not in dates:
                dates.append(day_key)
            status["trading_dates"] = dates
        pnl = trade_event.get("pnl")
        if pnl is not None:
            try:
                pnl_pct = float(pnl) / start_equity
                status["worst_trade_pct"] = min(float(status.get("worst_trade_pct", 0.0)), pnl_pct)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        append_event({"ts": _iso(ts), "strategy": strategy, "symbol": symbol, **trade_event},
                     events_path)

    day_peak_rel = float(status.get("day_peak_rel", rel))
    daily_floor_rel = day_peak_rel - cfg.daily_dd_pct
    total_floor_rel = 1.0 - cfg.max_loss_pct
    daily_cushion = rel - daily_floor_rel
    total_cushion = rel - total_floor_rel
    min_cushion = min(daily_cushion, total_cushion)
    target = cfg.profit_target_pct
    trading_days = len(status.get("trading_dates", []))
    worst_trade = float(status.get("worst_trade_pct", 0.0))

    if rel <= daily_floor_rel:
        rule_state = "breach_daily"
    elif rel <= total_floor_rel:
        rule_state = "breach_total"
    elif worst_trade <= -cfg.max_trade_loss_pct:
        rule_state = "trade_loss_violation"
    elif target is not None and rel >= 1.0 + target and trading_days >= cfg.min_trading_days:
        rule_state = "passed"
    elif min_cushion <= cfg.halt_buffer_pct:
        rule_state = "halt_zone"
    elif min_cushion <= cfg.warn_buffer_pct:
        rule_state = "warning"
    else:
        rule_state = "running"

    account_equity = cfg.account_size * rel
    status.update({
        "updated_at": _iso(ts),
        "account_size": cfg.account_size,
        "account_equity": account_equity,
        "account_pnl_pct": rel - 1.0,
        "daily_dd_pct": cfg.daily_dd_pct,
        "max_loss_pct": cfg.max_loss_pct,
        "profit_target_pct": target,
        "min_trading_days": cfg.min_trading_days,
        "trading_days": trading_days,
        "daily_floor_equity": cfg.account_size * daily_floor_rel,
        "total_floor_equity": cfg.account_size * total_floor_rel,
        "daily_cushion_pct": daily_cushion,
        "total_cushion_pct": total_cushion,
        "min_cushion_pct": min_cushion,
        "rule_state": rule_state,
        "hard_stop": rule_state in {
            "breach_daily", "breach_total", "trade_loss_violation", "halt_zone",
        },
    })

    if rule_state != status.get("last_rule_state"):
        append_event({
            "ts": _iso(ts),
            "strategy": strategy,
            "symbol": symbol,
            "kind": "rule_state",
            "rule_state": rule_state,
            "account_pnl_pct": round(rel - 1.0, 6),
            "min_cushion_pct": round(min_cushion, 6),
        }, events_path)
        status["last_rule_state"] = rule_state
    status["status"] = rule_state
    save_status(status, status_path)
    return status


def should_block_new_entries(status: dict[str, Any]) -> bool:
    return bool(status.get("hard_stop"))


def format_status(status: dict[str, Any]) -> str:
    if not status:
        return "CFT monitor sin datos. Arranca el paper PropSwing o ejecuta un status."
    pnl = float(status.get("account_pnl_pct", 0.0)) * 100
    daily = float(status.get("daily_cushion_pct", 0.0)) * 100
    total = float(status.get("total_cushion_pct", 0.0)) * 100
    target = status.get("profit_target_pct")
    target_s = "funded" if target is None else f"{float(target) * 100:.1f}%"
    return (
        f"CFT {status.get('phase', '?').upper()} {status.get('rule_state', '?')}\n"
        f"Equity: ${float(status.get('account_equity', 0.0)):,.0f} "
        f"({pnl:+.2f}%) / target {target_s}\n"
        f"Cushion daily {daily:.2f}pp | total {total:.2f}pp\n"
        f"Trading days: {status.get('trading_days', 0)}/{status.get('min_trading_days', 0)}\n"
        f"Updated: {status.get('updated_at', '?')}"
    )
