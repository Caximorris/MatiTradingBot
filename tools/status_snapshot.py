"""Pure helpers for the multi-portfolio ``main.py status`` view."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.paper_bots import bot_label, is_operable_bot_name, paper_state_path
from tools.paper_snapshot import read_paper_balances

MADRID = ZoneInfo("Europe/Madrid")


def _execution_symbol(symbol: str, config: dict) -> str:
    """Return the real execution pair while preserving the strategy/feed pair."""
    if config.get("execution") != "okx_demo" or not config.get("execution_quote"):
        return symbol
    base, sep, _quote = symbol.rpartition("-")
    return f"{base}{sep}{str(config['execution_quote']).upper()}" if sep else symbol


def _display_label(name: str, config: dict) -> str:
    if name.startswith("prop_swing"):
        return "prop"
    return bot_label(name, config)


def build_bot_records(states: list) -> list[dict]:
    """Detach runnable BotState rows and exclude internal persistence rows."""
    out: list[dict] = []
    for state in states:
        if not is_operable_bot_name(state.strategy_name, state.symbol):
            continue
        config = state.get_config() or {}
        out.append({
            "label": _display_label(state.strategy_name, config),
            "name": state.strategy_name,
            "signal_symbol": state.symbol,
            "execution_symbol": _execution_symbol(state.symbol, config),
            "execution_venue": (
                "OKX Demo" if config.get("execution") == "okx_demo" else "simulado"
            ),
            "is_active": bool(state.is_active),
            "last_run": state.last_run,
            "total_pnl": Decimal(str(state.total_pnl or 0)),
            "config": config,
        })
    return out


def build_paper_portfolios(records: list[dict], runtime_dir: Path) -> list[dict]:
    """Load each isolated wallet and expose Demo's real quote currency in reporting."""
    out: list[dict] = []
    for record in records:
        config = record["config"]
        wallet = paper_state_path(config.get("paper_portfolio_id"), runtime_dir)
        balances = read_paper_balances(wallet)
        base, _, strategy_quote = record["signal_symbol"].partition("-")
        execution_quote = str(config.get("execution_quote") or strategy_quote).upper()
        # OKXDemoClient intentionally aliases USDC -> USDT for frozen-strategy
        # compatibility. Reporting reverses only the label; it never mutates the wallet.
        if execution_quote != strategy_quote:
            quote_balance = balances.get(
                execution_quote, balances.get(strategy_quote, Decimal("0")),
            )
        else:
            quote_balance = balances.get(strategy_quote, Decimal("0"))
        out.append({
            **record,
            "base_currency": base,
            "base_balance": balances.get(base, Decimal("0")),
            "quote_currency": execution_quote,
            "quote_balance": quote_balance,
            "wallet_path": wallet,
            "wallet_exists": wallet.exists(),
            "quote_is_alias": execution_quote != strategy_quote,
        })
    return out


def format_madrid(ts: datetime | None) -> str:
    """Render DB UTC timestamps in the operator's Europe/Madrid timezone."""
    if ts is None:
        return "—"
    aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return aware.astimezone(MADRID).strftime("%d/%m %H:%M %Z")


def format_iso_madrid(value: str | None) -> str:
    """Parse an ISO UTC value and render it for the Europe/Madrid operator."""
    if not value:
        return "?"
    try:
        return format_madrid(datetime.fromisoformat(value))
    except (TypeError, ValueError):
        return str(value)
