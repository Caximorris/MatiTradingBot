"""Audited reconciliation between the OKX Demo mirror and Swing JSONL.

This command never places an order and never rewrites an existing journal line. It
appends a distinct ``RECONCILE`` event so reporting can adopt the current holdings
without misrepresenting an out-of-band correction as a strategy BUY or SELL.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


RECONCILE_GAP_PP = Decimal("15")


@dataclass(frozen=True)
class ReconcileResult:
    status: str  # appended | already_reconciled | already_aligned
    event: dict | None
    gap_pp: Decimal


def _decimal_token(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _load_wallet(path: Path) -> tuple[dict, dict[str, Decimal]]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el espejo Demo: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Espejo Demo invalido: {path}") from exc
    if raw.get("mirror_of") != "okx_demo_trading":
        raise ValueError(
            f"{path} no declara mirror_of=okx_demo_trading; se rechaza reconciliarlo"
        )
    balances = {
        str(ccy).upper(): Decimal(str(amount))
        for ccy, amount in raw.get("balances", {}).items()
    }
    return raw, balances


def _read_journal(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _fingerprint(strategy: str, symbol: str, base_qty: Decimal, cash: Decimal) -> str:
    canonical = "|".join((
        strategy,
        symbol,
        _decimal_token(base_qty),
        _decimal_token(cash),
    ))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reconcile_demo_journal(
    *,
    strategy: str,
    symbol: str,
    wallet_path: Path,
    journal_path: Path,
    price: Decimal,
    execution_quote: str,
    reason: str,
    now: datetime | None = None,
) -> ReconcileResult:
    """Append one idempotent audit event when Demo wallet and journal differ materially."""
    if price <= 0:
        raise ValueError("El precio spot debe ser positivo")
    if not reason.strip():
        raise ValueError("La reconciliacion requiere un motivo de auditoria")

    base, sep, strategy_quote = symbol.upper().partition("-")
    if not sep:
        raise ValueError(f"Simbolo invalido: {symbol}")
    wallet_raw, balances = _load_wallet(wallet_path)
    base_qty = balances.get(base, Decimal("0"))
    # OKXDemoClient writes the execution quote under the strategy alias (USDT).
    cash = balances.get(strategy_quote)
    if cash is None:
        cash = balances.get(execution_quote.upper())
    if cash is None:
        raise ValueError(
            f"El espejo no contiene {strategy_quote} ni {execution_quote.upper()}"
        )
    if base_qty < 0 or cash < 0:
        raise ValueError("El espejo contiene un balance negativo")

    portfolio = base_qty * price + cash
    if portfolio <= 0:
        raise ValueError("La cartera Demo no tiene valor reconciliable")
    current_pct = (base_qty * price) / portfolio

    rows = [r for r in _read_journal(journal_path) if r.get("strategy") == strategy]
    if not rows:
        raise ValueError(f"No hay journal previo para {strategy}; no se puede preservar continuidad")
    # File order is the audit order. A later failed/incomplete operation must be
    # superseded by a new reconciliation even if an older row had the same wallet.
    last = rows[-1]
    last_pct = Decimal(str(last.get("btc_pct_after", 0)))
    gap_pp = abs(current_pct - last_pct) * Decimal("100")

    fingerprint = _fingerprint(strategy, symbol, base_qty, cash)
    if (
        last.get("direction") == "RECONCILE"
        and last.get("reconciliation", {}).get("fingerprint") == fingerprint
    ):
        return ReconcileResult("already_reconciled", last, gap_pp)
    if gap_pp <= RECONCILE_GAP_PP:
        return ReconcileResult("already_aligned", None, gap_pp)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    numbers = [int(r["num"]) for r in rows if str(r.get("num", "")).isdigit()]
    event = {
        "strategy": strategy,
        "symbol": symbol.upper(),
        "num": max(numbers, default=0) + 1,
        "timestamp": current.isoformat(),
        "direction": "RECONCILE",
        # JSONL keeps the established numeric schema; every calculation above uses Decimal.
        "price": float(price.quantize(Decimal("0.01"))),
        "qty": 0.0,
        "btc_pct_before": float(last_pct.quantize(Decimal("0.0001"))),
        "btc_pct_target": float(current_pct.quantize(Decimal("0.0001"))),
        "btc_pct_after": float(current_pct.quantize(Decimal("0.0001"))),
        "portfolio_usdt": float(portfolio.quantize(Decimal("0.01"))),
        "signals": ["manual_wallet_reconcile"],
        "reconciliation": {
            "kind": "out_of_band_balance_reconciliation",
            "reason": reason.strip(),
            "source_wallet": wallet_path.name,
            "wallet_updated_at": wallet_raw.get("updated_at"),
            "execution_quote": execution_quote.upper(),
            "mirror_quote_key": strategy_quote,
            "tracked_balances": {
                base: _decimal_token(base_qty),
                strategy_quote: _decimal_token(cash),
            },
            "fingerprint": fingerprint,
        },
    }

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")
    return ReconcileResult("appended", event, gap_pp)
