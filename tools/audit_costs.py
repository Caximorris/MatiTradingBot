"""Sensibilidad a costes: reaplica fee/slippage x1/x2/x3 sobre los mismos rebalanceos v4."""
import json
from datetime import datetime, timezone

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])  # portable (VM Linux / Windows)
JOURNAL = ROOT + r"\backtests\journal_swing_allocator_btc_usdt_BTCUSDT_1H_20260702_064622.json"
CACHE = ROOT + r"\data\cache\BTC-USDT_1H.json"

d = json.load(open(JOURNAL))
rebs = d["rebalances"]
cache = json.load(open(CACHE))
bars = sorted((int(r[0]), float(r[4])) for r in cache["bars"])
end_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
p_end = [c for t, c in bars if t <= end_ms][-1]

years = (end_ms - datetime.fromisoformat(rebs[0]["timestamp"]).timestamp() * 1000) / (365.25 * 86400e3)

notional = sum(r["qty"] * r["price"] for r in rebs)
print(f"rebalanceos: {len(rebs)} | notional total operado: {notional:,.0f} USDT")

for mult in (1, 2, 3):
    FEE = 0.001 * mult
    SLIP = 0.0005 * mult
    usdt, btc = 10000.0, 0.0
    skipped = 0
    for r in rebs:
        p, q = r["price"], r["qty"]
        if r["direction"] in ("INIT", "BUY"):
            pf = p * (1 + SLIP)
            cost = q * pf * (1 + FEE)
            if cost > usdt:  # ajustar qty a saldo disponible (como haria el bot)
                q = usdt / (pf * (1 + FEE)) * 0.999
                cost = q * pf * (1 + FEE)
                skipped += 1
            usdt -= cost; btc += q
        else:
            q = min(q, btc)
            pf = p * (1 - SLIP)
            usdt += q * pf * (1 - FEE); btc -= q
    final = usdt + btc * p_end
    cagr = (final / 10000.0) ** (1 / years) - 1
    print(f"costes x{mult} (fee {FEE:.2%}, slip {SLIP:.3%}): final {final:,.0f} | CAGR {cagr:+.1%} | ajustes saldo {skipped}")

# B&H con coste de 1 compra
bh = 10000.0 / (bars[0][1] if False else next(c for t, c in bars if t >= datetime(2015,1,1,tzinfo=timezone.utc).timestamp()*1000)) * p_end
print(f"B&H bruto: {bh:,.0f} | CAGR B&H {(bh/10000)**(1/years)-1:+.1%}")

# alpha por fase de halving del tramo (fase en el momento del rebalanceo que ABRE el tramo)
from bisect import bisect_right
ts_list = [t for t, _ in bars]
FEE, SLIP = 0.001, 0.0005
usdt, btc = 10000.0, 0.0
events = []
for r in rebs:
    ts = datetime.fromisoformat(r["timestamp"]).timestamp() * 1000
    p, q = r["price"], r["qty"]
    if r["direction"] in ("INIT", "BUY"):
        usdt -= q * p * (1 + SLIP) * (1 + FEE); btc += q
    else:
        usdt += q * p * (1 - SLIP) * (1 - FEE); btc -= q
    events.append((ts, usdt, btc, r["signals"]))

import collections
phase_alpha = collections.defaultdict(lambda: 1.0)
for i in range(len(events)):
    t0 = events[i][0]
    t1 = events[i + 1][0] if i + 1 < len(events) else end_ms
    i0 = bisect_right(ts_list, t0) - 1; i1 = bisect_right(ts_list, t1) - 1
    pr0, pr1 = bars[i0][1], bars[i1][1]
    u, b = events[i][1], events[i][2]
    eq0, eq1 = u + b * pr0, u + b * pr1
    sigs = events[i][3]
    tag = "otros"
    for s in sigs:
        if "bear_onset" in s: tag = "bear_onset"; break
        if "bull_peak" in s or "post" in s: tag = "post/bull_peak"
        if s.startswith("regime_bear"): tag = max(tag, "regime_bear") if tag=="otros" else tag
    phase_alpha[tag] *= (eq1 / eq0) / (pr1 / pr0)
print("\nalpha multiplicativo por tipo de tramo (senal activa al abrir):")
for k, v in sorted(phase_alpha.items(), key=lambda x: -x[1]):
    print(f"  {k}: x{v:.3f}")
