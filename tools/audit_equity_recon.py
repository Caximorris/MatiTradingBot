"""Audit: reconstruye equity del Swing v4 desde el journal de rebalanceos + cache OHLCV.
Calcula: validacion de reconstruccion, retornos por anio vs B&H, max DD por anio,
alpha por anio, concentracion del edge, y escenario sin-2020-2021.
"""
import json
from datetime import datetime, timezone
from bisect import bisect_right

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])  # portable (VM Linux / Windows)
JOURNAL = ROOT + r"\backtests\journal_swing_allocator_btc_usdt_BTCUSDT_1H_20260702_064622.json"
CACHE = ROOT + r"\data\cache\BTC-USDT_1H.json"

FEE = 0.001
SLIP = 0.0005  # realistic

d = json.load(open(JOURNAL))
rebs = d["rebalances"]
cfg = d["meta"].get("resolved_config", {})

cache = json.load(open(CACHE))
bars = [(int(r[0]), float(r[4])) for r in cache["bars"]]  # ts_ms, close
bars.sort()
ts_list = [b[0] for b in bars]

start_ms = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
end_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
sim = [(t, c) for t, c in bars if start_ms <= t <= end_ms]

# --- reconstruccion de holdings ---
usdt = 10000.0
btc = 0.0
events = []
for r in rebs:
    ts = datetime.fromisoformat(r["timestamp"]).timestamp() * 1000
    p = r["price"]; q = r["qty"]
    if r["direction"] in ("INIT", "BUY"):
        pf = p * (1 + SLIP)
        cost = q * pf * (1 + FEE)
        usdt -= cost; btc += q
    else:
        pf = p * (1 - SLIP)
        usdt += q * pf * (1 - FEE); btc -= q
    events.append((ts, usdt, btc, r))

# validar contra portfolio_usdt del journal (total antes del trade siguiente)
errs = []
for i in range(1, len(events)):
    ts, _, _, r = events[i]
    u_prev, b_prev = events[i - 1][1], events[i - 1][2]
    total_recon = u_prev + b_prev * r["price"]
    errs.append(abs(total_recon - r["portfolio_usdt"]) / r["portfolio_usdt"])
print(f"validacion reconstruccion: err rel max {max(errs):.4%}, medio {sum(errs)/len(errs):.4%}")

# --- equity horaria ---
ev_ts = [e[0] for e in events]
equity = []
for t, c in sim:
    i = bisect_right(ev_ts, t) - 1
    if i < 0:
        equity.append((t, 10000.0, 0.0))
    else:
        u, b = events[i][1], events[i][2]
        equity.append((t, u + b * c, b * c / (u + b * c) if (u + b * c) > 0 else 0))

print(f"equity final reconstruida: {equity[-1][1]:,.0f} (journal: {d['statistics']['final_balance_usdt']:,.0f})")

p0 = sim[0][1]
print(f"\nBTC 2015-01-01: ${p0:,.0f}  ->  2026-01-01: ${sim[-1][1]:,.0f}  (B&H x{sim[-1][1]/p0:,.1f})")
bh_final = 10000.0 / p0 * sim[-1][1] * (1 - FEE - SLIP)
print(f"B&H final: {bh_final:,.0f} | estrategia: {equity[-1][1]:,.0f} | ratio {equity[-1][1]/bh_final:.2f}x")

# --- por anio: retorno estrategia, retorno B&H, max DD estrategia, exposicion media ---
def year_of(t):
    return datetime.fromtimestamp(t / 1000, tz=timezone.utc).year

print(f"\n{'anio':>5} {'strat%':>9} {'B&H%':>9} {'alpha_pp':>9} {'maxDD%':>8} {'expo_med':>8}")
years = {}
for (t, eq, expo) in equity:
    years.setdefault(year_of(t), []).append((t, eq, expo))

cum_log_alpha = {}
for y in sorted(years):
    rows = years[y]
    e0, e1 = rows[0][1], rows[-1][1]
    # B&H del anio con los mismos timestamps
    c0 = sim[bisect_right(ts_list, rows[0][0]) - 1][1] if False else None
    p_start = next(c for t, c in sim if year_of(t) == y)
    p_end = [c for t, c in sim if year_of(t) == y][-1]
    r_s = (e1 / e0 - 1) * 100
    r_b = (p_end / p_start - 1) * 100
    peak = rows[0][1]; mdd = 0.0
    for _, eq, _ in rows:
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    expo_med = sum(x[2] for x in rows) / len(rows)
    cum_log_alpha[y] = (e1 / e0) / (p_end / p_start)
    print(f"{y:>5} {r_s:>+9.1f} {r_b:>+9.1f} {r_s - r_b:>+9.1f} {mdd*100:>8.1f} {expo_med:>8.2f}")

# --- concentracion del alpha: producto de ratios anuales ---
print("\nratio estrategia/B&H por anio (>1 = anio con alpha):")
tot = 1.0
for y in sorted(cum_log_alpha):
    tot *= cum_log_alpha[y]
    print(f"  {y}: {cum_log_alpha[y]:.3f}")
print(f"  producto total: {tot:.2f}x")

# --- escenario: excluir 2020-2021 (encadenar el resto) ---
tot_ex = 1.0
for y in sorted(cum_log_alpha):
    if y not in (2020, 2021):
        tot_ex *= cum_log_alpha[y]
print(f"alpha acumulado excluyendo 2020-2021: {tot_ex:.2f}x | excluyendo 2017-2018: ", end="")
tot_ex2 = 1.0
for y in sorted(cum_log_alpha):
    if y not in (2017, 2018):
        tot_ex2 *= cum_log_alpha[y]
print(f"{tot_ex2:.2f}x")

# --- los 10 mayores saltos de alpha entre rebalanceos consecutivos ---
print("\nmayores contribuciones de alpha por tramo (entre rebalanceos):")
segs = []
for i in range(len(events)):
    t0 = events[i][0]
    t1 = events[i + 1][0] if i + 1 < len(events) else sim[-1][0]
    # precios en t0/t1
    i0 = bisect_right(ts_list, t0) - 1; i1 = bisect_right(ts_list, t1) - 1
    pr0, pr1 = bars[i0][1], bars[i1][1]
    u, b = events[i][1], events[i][2]
    eq0 = u + b * pr0; eq1 = u + b * pr1
    if eq0 <= 0 or pr0 <= 0:
        continue
    seg_alpha = (eq1 / eq0) / (pr1 / pr0)
    segs.append((seg_alpha, datetime.fromtimestamp(t0/1000, tz=timezone.utc).date(),
                 datetime.fromtimestamp(t1/1000, tz=timezone.utc).date(),
                 events[i][3]["btc_pct_after"], pr0, pr1))
segs.sort(reverse=True)
for a, d0, d1, pct, pr0, pr1 in segs[:8]:
    print(f"  {d0} -> {d1} | btc {pct:.0%} | BTC ${pr0:,.0f}->${pr1:,.0f} | alpha x{a:.3f}")
print("  ... peores:")
for a, d0, d1, pct, pr0, pr1 in segs[-5:]:
    print(f"  {d0} -> {d1} | btc {pct:.0%} | BTC ${pr0:,.0f}->${pr1:,.0f} | alpha x{a:.3f}")
