"""Peor consumo de stable en un solo rebalanceo BUY (input de diseño del buffer E2).

draw = fraccion del stable pre-rebalanceo consumida por la compra
     = (pct_after - pct_before) / (1 - pct_before)
"""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
rebs = [r for r in data["rebalances"] if r["direction"] == "BUY"]

rows = []
for r in rebs:
    pre, post = r["btc_pct_before"], r["btc_pct_after"]
    stable_frac_pre = 1.0 - pre
    if stable_frac_pre <= 0:
        continue
    draw = (post - pre) / stable_frac_pre
    rows.append((draw, r["timestamp"][:10], pre, post,
                 r["portfolio_usdt"] * stable_frac_pre))

rows.sort(reverse=True)
print(f"{path.name}: {len(rows)} BUYs")
print("top draws (fraccion del stable consumida en UN rebalanceo):")
for draw, d, pre, post, stable_usd in rows[:8]:
    print(f"  {d}  {pre:.2f}->{post:.2f}  draw {draw*100:5.1f}%  (stable pre ${stable_usd:,.0f})")
over80 = sum(1 for r in rows if r[0] > 0.80)
over50 = sum(1 for r in rows if r[0] > 0.50)
print(f"BUYs con draw >80%: {over80} | >50%: {over50} | total: {len(rows)}")
