#!/usr/bin/env python
"""Smoke test MANUAL del cliente OKX demo — primera vez contra la API autenticada real.

Ejercita, paso a paso y con salida legible, todo lo que el bot demo usara en produccion:
credenciales, balance, ticker real, orden market BUY (con tgtCcy=base_ccy), fill real,
limit lejana + cancel, market SELL de vuelta, y el espejo paper_state_okx_demo.json.
No toca la estrategia ni la DB de bots. Dinero: SIEMPRE demo (x-simulated-trading:1).

Uso:
  python tools/okx_demo_smoke.py                  # solo lectura: balance + ticker
  python tools/okx_demo_smoke.py --trade          # + ciclo buy/limit-cancel/sell (size 0.001 BTC)
  python tools/okx_demo_smoke.py --trade --size 0.002
  python tools/okx_demo_smoke.py --flatten        # vende todo lo no-USDT a USDT (prepara cuenta
                                                  # solo-USDT para que el bot haga el INIT)

Requiere OKX_DEMO_API_KEY/SECRET_KEY/PASSPHRASE en .env (key creada DENTRO del modo
demo trading de OKX; la real da error 50119).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Pares spot demo soportados para --flatten (solo los mayores; el resto se reporta y se deja).
_FLATTEN_QUOTE = "USDT"
# OKX spot: tamaño minimo aproximado por par (evitar rechazos 51008 por polvo).
_MIN_SZ = {
    "BTC": Decimal("0.00001"),
    "ETH": Decimal("0.001"),
    "SOL": Decimal("0.01"),
}


def _fmt_balance(bal: dict[str, Decimal]) -> str:
    if not bal:
        return "  (vacio)"
    return "\n".join(f"  {ccy}: {amt}" for ccy, amt in sorted(bal.items()))


def _print_order(label: str, result) -> None:
    print(f"\n[{label}] status={result.status} id={result.order_id or '-'}")
    print(f"  side={result.side} type={result.order_type} size={result.size}")
    print(f"  filled_price={result.filled_price} filled_qty={result.filled_qty}")
    print(f"  fee={result.fee} {result.fee_currency}")
    if result.error:
        print(f"  ERROR: {result.error}")


def cmd_read_only(client, symbol: str) -> None:
    print("\n=== 1. BALANCE DEMO (AccountAPI flag=1) ===")
    bal = client.get_balance()
    print(_fmt_balance(bal))

    print(f"\n=== 2. TICKER {symbol} (feed REAL flag=0) ===")
    px = client.get_ticker(symbol)
    print(f"  {symbol} = {px}")

    print("\n=== 3. ORDENES ABIERTAS ===")
    open_orders = client.get_open_orders(symbol)
    print(f"  {len(open_orders)} abiertas")
    for o in open_orders:
        print(f"  - {o.get('ordId')} {o.get('side')} {o.get('ordType')} sz={o.get('sz')} px={o.get('px')}")

    print("\n=== 4. ESPEJO paper_state ===")
    mirror = client._mirror_path
    if mirror.exists():
        data = json.loads(mirror.read_text(encoding="utf-8"))
        print(f"  {mirror} OK -> balances={data.get('balances')}")
    else:
        print(f"  {mirror} NO existe (get_balance deberia haberlo escrito)")


def cmd_trade_cycle(client, symbol: str, size: Decimal) -> int:
    base, quote = symbol.split("-")
    px = client.get_ticker(symbol)
    if px <= 0:
        print("ABORT: ticker invalido, no se puede dimensionar la prueba.")
        return 1
    notional = size * px
    print(f"\nCiclo de prueba: {size} {base} (~{notional:.2f} {quote} @ {px})")

    bal0 = client.get_balance()
    usdt0, btc0 = bal0.get(quote, Decimal("0")), bal0.get(base, Decimal("0"))
    if usdt0 < notional * Decimal("1.01"):
        print(f"ABORT: {quote} insuficiente en demo ({usdt0}) para ~{notional:.2f}.")
        return 1

    # --- market BUY: el camino critico (tgtCcy=base_ccy) ---
    r_buy = client.place_order(symbol, "buy", "market", size, strategy="smoke")
    _print_order("MARKET BUY", r_buy)
    if r_buy.status != "filled":
        print("FALLO: la compra market no se ejecuto.")
        return 1
    # Verificacion del bug tgtCcy: si OKX hubiera interpretado sz como USDT, filled_qty
    # seria ~size/px (miles de veces menor). Toleramos fees/redondeos del 5%.
    if r_buy.filled_qty < size * Decimal("0.95"):
        print(f"FALLO tgtCcy?: pedimos {size} {base} y llego {r_buy.filled_qty} {base}.")
        return 1
    print(f"  OK: qty en moneda BASE confirmada ({r_buy.filled_qty} {base})")

    # --- limit SELL lejana + cancel: camino limit y cancel_order ---
    far_px = (px * Decimal("1.5")).quantize(Decimal("0.1"))
    r_lim = client.place_order(symbol, "sell", "limit", size, price=far_px, strategy="smoke")
    _print_order("LIMIT SELL (lejana, se cancela)", r_lim)
    if r_lim.status == "open":
        time.sleep(0.5)
        ok = client.cancel_order(r_lim.order_id, symbol)
        print(f"  cancel_order -> {ok}")
        if not ok:
            print("FALLO: no se pudo cancelar la limit. Cancelala a mano en OKX.")
            return 1
    else:
        print("AVISO: la limit no quedo abierta (revisar arriba).")

    # --- market SELL: deshacer la compra ---
    sell_sz = min(r_buy.filled_qty, size)
    r_sell = client.place_order(symbol, "sell", "market", sell_sz, strategy="smoke")
    _print_order("MARKET SELL", r_sell)
    if r_sell.status != "filled":
        print(f"FALLO: la venta no se ejecuto — quedan ~{sell_sz} {base} comprados en demo.")
        return 1

    # --- balance final + historial ---
    bal1 = client.get_balance()
    usdt1, btc1 = bal1.get(quote, Decimal("0")), bal1.get(base, Decimal("0"))
    print(f"\nBalance {quote}: {usdt0} -> {usdt1} (delta {usdt1 - usdt0}, ~2x fee esperado)")
    print(f"Balance {base}:  {btc0} -> {btc1}")
    hist = client.get_order_history(symbol, limit=5)
    print(f"\nUltimas {len(hist)} ordenes en OKX demo:")
    for o in hist:
        print(f"  - {o.get('ordId')} {o.get('side')} {o.get('ordType')} sz={o.get('sz')} "
              f"avgPx={o.get('avgPx')} state={o.get('state')}")
    print("\nSMOKE TRADE: OK")
    return 0


def cmd_flatten(client) -> int:
    """Vende a USDT todo activo no-USDT con par directo. Deja la cuenta lista para INIT."""
    bal = client.get_balance()
    print("Balance actual:\n" + _fmt_balance(bal))
    rc = 0
    for ccy, amt in sorted(bal.items()):
        if ccy == _FLATTEN_QUOTE or amt <= 0:
            continue
        min_sz = _MIN_SZ.get(ccy)
        if min_sz is None:
            print(f"  SKIP {ccy} {amt}: par no soportado por --flatten (venderlo a mano en OKX).")
            continue
        if amt < min_sz:
            print(f"  SKIP {ccy} {amt}: por debajo del minimo {min_sz} (polvo).")
            continue
        symbol = f"{ccy}-{_FLATTEN_QUOTE}"
        r = client.place_order(symbol, "sell", "market", amt, strategy="smoke-flatten")
        _print_order(f"FLATTEN {symbol}", r)
        if r.status != "filled":
            rc = 1
    print("\nBalance final:\n" + _fmt_balance(client.get_balance()))
    return rc


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--size", default="0.001", help="Tamaño en moneda BASE para --trade")
    p.add_argument("--trade", action="store_true", help="Ejecuta el ciclo buy/limit-cancel/sell")
    p.add_argument("--flatten", action="store_true", help="Vende todo lo no-USDT a USDT")
    args = p.parse_args()

    from config.settings import load_settings
    from core.okx_demo_client import OKXDemoClient

    settings = load_settings()
    print("Instanciando OKXDemoClient (valida credenciales + primer sync de balance)...")
    try:
        client = OKXDemoClient(settings)
    except Exception as exc:
        print(f"FALLO al instanciar: {exc}")
        return 1
    print("OK: cliente demo operativo.")

    cmd_read_only(client, args.symbol)
    rc = 0
    if args.flatten:
        rc = cmd_flatten(client) or rc
    if args.trade:
        rc = cmd_trade_cycle(client, args.symbol, Decimal(args.size)) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
