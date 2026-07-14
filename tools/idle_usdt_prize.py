"""Cuantifica el premio de poner yield al balance stable ocioso del Swing Allocator.

Lee un journal de swing (rebalances con timestamp, btc_pct_after, portfolio_usdt),
reconstruye el balance stable USD entre rebalanceos (constante entre eventos) y calcula:
  - stable-dollar-days totales y % medio del portfolio en stable (time-weighted aprox)
  - uplift simple (sin compounding) a 2/4/6% APR, en $ y en pp de CAGR
  - tramos continuos con >60% stable (las "ventanas muertas" que motivan la idea)

Aproximacion consciente: entre rebalanceos el stable USD es constante pero el valor
del portfolio varia con BTC; usamos stable/portfolio SOLO en el instante del rebalanceo
para el % medio, y el stable USD constante para los dollar-days (que es lo que paga APR).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

APRS = [0.02, 0.04, 0.06]


def parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def analyze(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    stats = data.get("statistics", {})
    rebs = data.get("rebalances", [])
    if not rebs:
        print(f"{path.name}: sin rebalances, skip")
        return

    to_date = meta.get("to_date")
    end = parse_ts(to_date) if to_date else parse_ts(rebs[-1]["timestamp"])
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    # segmentos: [ts_i, ts_{i+1}) con stable_i = portfolio_i * (1 - pct_after_i)
    seg = []
    for i, r in enumerate(rebs):
        t0 = parse_ts(r["timestamp"])
        t1 = parse_ts(rebs[i + 1]["timestamp"]) if i + 1 < len(rebs) else end
        days = max((t1 - t0).total_seconds() / 86400.0, 0.0)
        stable_usd = r["portfolio_usdt"] * (1.0 - r["btc_pct_after"])
        seg.append((t0, t1, days, stable_usd, r["btc_pct_after"]))

    total_days = sum(s[2] for s in seg)
    stable_dollar_days = sum(s[2] * s[3] for s in seg)
    # % medio stable, ponderado por tiempo (share medido en el instante del rebalanceo)
    w_share = sum(s[2] * (1.0 - s[4]) for s in seg) / total_days if total_days else 0.0

    init_bal = stats.get("initial_balance_usdt")
    final_bal = stats.get("final_balance_usdt")
    years = total_days / 365.25

    print(f"\n=== {path.name}")
    print(f"    ventana {meta.get('from_date')} -> {meta.get('to_date')} | costes {meta.get('cost_mode')}")
    ov = meta.get("config_overrides") or meta.get("resolved_config", {})
    keyflags = {k: v for k, v in (ov or {}).items()
                if k in ("use_phase_policy_router", "use_funding_overlay",
                         "regime_off_on_bear_onset", "daily_on_closed_only")}
    print(f"    flags: {keyflags or '(defaults)'}")
    print(f"    balance {init_bal} -> {final_bal} | {len(rebs)} eventos | {total_days:.0f} dias ({years:.1f} anos)")
    print(f"    stable share medio (time-weighted): {w_share*100:.1f}%")
    print(f"    stable-dollar-days: ${stable_dollar_days:,.0f}")

    if final_bal and years > 0:
        base_cagr = (final_bal / init_bal) ** (1 / years) - 1
        for apr in APRS:
            extra = stable_dollar_days / 365.25 * apr
            new_final = final_bal + extra
            new_cagr = (new_final / init_bal) ** (1 / years) - 1
            print(f"    APR {apr*100:.0f}%: +${extra:,.0f} ({extra/final_bal*100:.2f}% del final) "
                  f"| CAGR {base_cagr*100:.2f}% -> {new_cagr*100:.2f}% (+{(new_cagr-base_cagr)*100:.2f}pp)")

    # ventanas muertas: tramos continuos con stable share > 60% en el evento
    runs, cur = [], None
    for t0, t1, days, stable_usd, pct_after in seg:
        if (1.0 - pct_after) > 0.60:
            if cur is None:
                cur = [t0, t1, days, stable_usd * days]
            else:
                cur[1] = t1
                cur[2] += days
                cur[3] += stable_usd * days
        else:
            if cur:
                runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    runs.sort(key=lambda r: -r[2])
    print(f"    ventanas continuas >60% stable: {len(runs)}")
    for r in runs[:6]:
        avg_stable = r[3] / r[2] if r[2] else 0
        print(f"      {r[0].date()} -> {r[1].date()} | {r[2]:.0f} dias | stable medio ${avg_stable:,.0f}")


if __name__ == "__main__":
    paths = [Path(p) for p in sys.argv[1:]]
    for p in paths:
        try:
            analyze(p)
        except Exception as exc:
            print(f"{p.name}: ERROR {exc}")
