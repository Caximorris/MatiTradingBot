"""Sensibilidad de v6-2 al retraso de ejecucion (medicion de robustez, ventana cerrada
solo para MEDIR — regla invariante SESSION.md §5).

Metodo: replay del journal ancla. Mismas decisiones (timestamps + btc_pct_target exactos
del journal v6-2 2015-2026 realistic), solo cambia el precio de ejecucion: la vela N horas
despues de la señal (open), con los mismos costes (fee 0.1% + slippage 5bps). El error de
modelo del replay se cancela comparando replay-0h vs replay-Nh (no vs el backtest real;
replay-0h se valida contra el ancla $9.53M como sanity).

Escenario A (--sells-delayed no): solo BUYs retrasados — modela stable fuera del exchange
(los SELL venden BTC que ya esta en el exchange, no se retrasan).
Escenario B: ambos lados retrasados (latencia total).

NO toca swing_allocator.py, ni el motor, ni el cache (solo lectura).
"""
import json
import sys
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path

FEE = 0.001      # realistic
SLIP = 0.0005    # 5 bps

ROOT = Path(r"C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot")
JOURNAL = ROOT / "backtests" / "journal_swing_allocator_btc_usdt_BTCUSDT_1H_20260714_143617.json"
CACHE = ROOT / "data" / "cache" / "BTC-USDT_1H.json"
END_MS = 1767225600000  # 2026-01-01T00:00:00Z — fin de la ventana del ancla


def load_bars():
    raw = json.loads(CACHE.read_text(encoding="utf-8"))
    ts = [int(r[0]) for r in raw["bars"]]
    op = [float(r[1]) for r in raw["bars"]]
    cl = [float(r[4]) for r in raw["bars"]]
    return ts, op, cl


def parse_ts_ms(s: str) -> int:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def replay(events, ts, op, cl, delay_h: float, delay_sells: bool):
    """Devuelve dict con final, cagr, max_dd, final_btc, peor fill delta."""
    delay_ms = int(delay_h * 3600 * 1000)
    sched = []
    for ev in events:
        sig_ms = parse_ts_ms(ev["timestamp"])
        is_buy = ev["direction"] in ("BUY", "INIT")
        d = delay_ms if (is_buy or delay_sells) else 0
        exec_ms = sig_ms + d
        i = bisect_left(ts, exec_ms)
        if i >= len(ts) or ts[i] > END_MS:
            continue  # cae fuera de la ventana — se pierde el evento (se reporta)
        sched.append((ts[i], i, ev))
    sched.sort(key=lambda x: x[0])

    usdt, btc = 10000.0, 0.0
    # indice de la primera vela con evento, para la curva de equity
    first_i = sched[0][1]
    ev_by_bar = {}
    for _, i, ev in sched:
        ev_by_bar.setdefault(i, []).append(ev)

    peak, max_dd = 0.0, 0.0
    for i in range(first_i, bisect_left(ts, END_MS)):
        if i in ev_by_bar:
            base = op[i]
            for ev in ev_by_bar[i]:
                target = ev["btc_pct_target"]
                port = usdt + btc * base
                delta_val = target * port - btc * base
                if delta_val > 0:  # BUY
                    price = base * (1 + SLIP)
                    notional = min(delta_val, usdt / (1 + FEE))
                    qty = notional / price
                    usdt -= notional * (1 + FEE)
                    btc += qty
                elif delta_val < 0:  # SELL
                    price = base * (1 - SLIP)
                    qty = min(btc, -delta_val / base)
                    usdt += qty * price * (1 - FEE)
                    btc -= qty
        eq = usdt + btc * cl[i]
        if eq > peak:
            peak = eq
        else:
            dd = 1 - eq / peak
            if dd > max_dd:
                max_dd = dd

    final = usdt + btc * cl[bisect_left(ts, END_MS) - 1]
    years = (END_MS - ts[first_i]) / (365.25 * 86400 * 1000)
    cagr = (final / 10000.0) ** (1 / years) - 1
    return {"final": final, "cagr": cagr, "max_dd": max_dd, "btc": btc,
            "n_events": len(sched)}


def main():
    data = json.loads(JOURNAL.read_text(encoding="utf-8"))
    events = data["rebalances"]
    ts, op, cl = load_bars()

    print(f"journal: {JOURNAL.name} | {len(events)} eventos (incl INIT)")
    gaps = sorted(
        (parse_ts_ms(events[i + 1]["timestamp"]) - parse_ts_ms(events[i]["timestamp"]))
        / 3600000 for i in range(len(events) - 1))
    print(f"gap minimo entre eventos consecutivos: {gaps[0]:.0f}h "
          f"(p5 {gaps[len(gaps)//20]:.0f}h)")

    rows = []
    for delay, dsell in [(0, False), (6, False), (24, False), (48, False),
                         (72, False), (168, False), (24, True), (72, True)]:
        r = replay(events, ts, op, cl, delay, dsell)
        tag = "A buys" if not dsell else "B ambos"
        rows.append((delay, tag, r))

    base = rows[0][2]
    print(f"\n{'delay':>6} {'lado':>8} {'final $':>14} {'CAGR':>8} {'dCAGR':>7} "
          f"{'MaxDD':>8} {'BTC fin':>9} {'ev':>4}")
    for delay, tag, r in rows:
        print(f"{delay:>5}h {tag:>8} {r['final']:>14,.0f} {r['cagr']*100:>7.2f}% "
              f"{(r['cagr']-base['cagr'])*100:>+6.2f}pp {r['max_dd']*100:>7.2f}% "
              f"{r['btc']:>9.4f} {r['n_events']:>4}")
    print(f"\nsanity replay-0h vs ancla $9,532,750: "
          f"ratio {base['final']/9532749.59:.4f} (validez del modelo de replay)")


if __name__ == "__main__":
    sys.exit(main())
