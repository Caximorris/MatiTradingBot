"""
N2 (PLAN B, HYROTRADER_PLAN seccion 13) — screens de alfa NO-indicador sobre datos existentes.

NO construye estrategias: mide si existe un efecto condicional estable por anios.
Screens:
  A) Estacionalidad por hora del dia UTC (fwd 1H) — incluye settlements 00/08/16.
  B) Funding extremo (OKX BTC-USDT-SWAP, por settlement, desde nov-2018): funding en
     percentil alto/bajo TRAILING 30d -> retorno fwd 24h/72h. Cache en data/cache/.
  C) Dia de la semana (retorno diario close->close).
  D) Post-barrida: barra 1H con rango > p99 del anio -> fwd 1h/4h/24h por direccion.

Metrica: media en bps + consistencia (# anios con el mismo signo). Criterio del plan:
efecto estable en >=6 de 8 anios (aqui 2015-2025, >=8/11 o >=6/7 para funding).
Barra de tradability standalone: ~30 bps/trade (round trip realistic); por debajo,
solo vale como FILTRO/condicionador de un motor 4H (N4).

Uso: python tools/alpha_screens.py [--symbol BTC-USDT] [--skip-funding]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

FROM_YEAR = 2015


def load_ohlcv(symbol: str) -> pd.DataFrame:
    raw = json.load(open(ROOT / "data" / "cache" / f"{symbol}_1H.json"))
    bars = raw["bars"] if isinstance(raw, dict) else raw
    df = pd.DataFrame(bars, columns=["ts", "o", "h", "l", "c", "v"])
    for col in ("o", "h", "l", "c", "v"):
        df[col] = df[col].astype(float)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df[df["dt"].dt.year >= FROM_YEAR].reset_index(drop=True)
    df["year"] = df["dt"].dt.year
    df["hour"] = df["dt"].dt.hour
    # Retornos forward close->close (en bps)
    c = df["c"].values
    for n, name in ((1, "f1"), (4, "f4"), (24, "f24"), (72, "f72")):
        f = np.full(len(c), np.nan)
        f[:-n] = (c[n:] / c[:-n] - 1.0) * 1e4
        df[name] = f
    return df


def consistency(df: pd.DataFrame, mask: pd.Series, col: str) -> tuple[float, str, int]:
    """(media bps, 'pos/anios', N) del subset frente a todos los anios con datos."""
    sub = df[mask]
    yr = sub.groupby("year")[col].mean().dropna()
    pos = int((yr > 0).sum())
    return float(sub[col].mean()), f"{pos}/{len(yr)}", int(sub[col].notna().sum())


def screen_hour_of_day(df: pd.DataFrame) -> None:
    print("\n== A) HORA DEL DIA UTC (fwd 1H, bps) ==")
    base = df["f1"].mean()
    print(f"base incondicional: {base:+.2f} bps/h")
    rows = []
    for hh in range(24):
        m, cons, n = consistency(df, df["hour"] == hh, "f1")
        rows.append((hh, m, cons, n))
    rows.sort(key=lambda r: r[1])
    for hh, m, cons, n in rows:
        mark = " <- settlement" if hh in (0, 8, 16) else ""
        print(f"  h{hh:02d}: {m:+7.2f} bps | anios+ {cons} | n={n}{mark}")


def screen_weekday(df: pd.DataFrame) -> None:
    print("\n== C) DIA DE LA SEMANA (retorno diario close 00:00, bps) ==")
    d0 = df[df["hour"] == 0].copy()
    d0["wd"] = d0["dt"].dt.dayofweek
    names = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
    for wd in range(7):
        m, cons, n = consistency(d0, d0["wd"] == wd, "f24")
        print(f"  {names[wd]}: {m:+7.2f} bps | anios+ {cons} | n={n}")


def screen_sweep(df: pd.DataFrame) -> None:
    print("\n== D) POST-BARRIDA (rango 1H > p99 del anio; fwd por direccion, bps) ==")
    rng = (df["h"] - df["l"]) / df["c"] * 1e4
    p99 = rng.groupby(df["year"]).transform(lambda s: s.quantile(0.99))
    swept = rng > p99
    up = swept & (df["c"] > df["o"])
    dn = swept & (df["c"] < df["o"])
    for label, mask in (("barrida ALCISTA", up), ("barrida BAJISTA", dn)):
        parts = []
        for col in ("f1", "f4", "f24"):
            m, cons, n = consistency(df, mask, col)
            parts.append(f"{col}={m:+7.2f} ({cons})")
        print(f"  {label}: {' | '.join(parts)} | n={int(mask.sum())}")


# ---------------------------------------------------------------------------
# B) Funding extremo (OKX, por settlement)
# ---------------------------------------------------------------------------

def fetch_funding(inst_id: str) -> pd.DataFrame:
    """Funding por settlement desde BYBIT (exchange objetivo; OKX solo sirve ~3 meses).
    Pagina hacia atras con endTime hasta agotar historico (~2020 en BTCUSDT)."""
    sym = inst_id.replace("-", "").replace("USDTSWAP", "USDT")
    cache = ROOT / "data" / "cache" / f"funding_bybit_{sym}.json"
    if cache.exists():
        rows = json.load(open(cache))
    else:
        rows, end = [], None
        url0 = (f"https://api.bybit.com/v5/market/funding/history"
                f"?category=linear&symbol={sym}&limit=200")
        for _ in range(200):
            url = url0 + (f"&endTime={end}" if end else "")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            page = data.get("result", {}).get("list", [])
            if not page:
                break
            rows += [(int(r["fundingRateTimestamp"]), float(r["fundingRate"]))
                     for r in page]
            end = int(page[-1]["fundingRateTimestamp"]) - 1
            time.sleep(0.2)
        json.dump(rows, open(cache, "w"))
        print(f"# funding Bybit cacheado: {len(rows)} settlements -> {cache.name}")
    df = pd.DataFrame(rows, columns=["ts", "rate"]).sort_values("ts").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def screen_funding(df: pd.DataFrame, symbol: str) -> None:
    print("\n== B) FUNDING EXTREMO (percentil trailing 30d = 90 settlements) ==")
    fu = fetch_funding(f"{symbol.split('-')[0]}-USDT-SWAP")
    if len(fu) < 500:
        print("  datos de funding insuficientes; screen omitido")
        return
    r = fu["rate"]
    lo = r.rolling(90).quantile(0.05).shift(1)
    hi = r.rolling(90).quantile(0.95).shift(1)
    fu["ext_hi"] = r > hi     # crowding long
    fu["ext_lo"] = r < lo     # crowding short
    # Mapear cada settlement a la barra 1H siguiente (evita lookahead: senal en t,
    # retorno desde la primera barra posterior)
    px = df[["dt", "f24", "f72", "year"]].copy()
    fu = pd.merge_asof(fu.sort_values("dt"), px.sort_values("dt"),
                       on="dt", direction="forward")
    print(f"  settlements: {len(fu)} ({fu['dt'].iloc[0].date()} -> {fu['dt'].iloc[-1].date()})"
          f" | rate medio {r.mean()*1e4:+.2f} bps/8h")
    base24 = fu["f24"].mean()
    print(f"  base incondicional fwd24: {base24:+.2f} bps")
    for label, mask in (("funding>p95 (longs crowded)", fu["ext_hi"]),
                        ("funding<p05 (shorts crowded)", fu["ext_lo"])):
        parts = []
        for col in ("f24", "f72"):
            m, cons, n = consistency(fu, mask, col)
            parts.append(f"{col}={m:+7.2f} ({cons})")
        print(f"  {label}: {' | '.join(parts)} | n={int(mask.sum())}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--skip-funding", action="store_true")
    args = p.parse_args()

    df = load_ohlcv(args.symbol)
    print(f"# {args.symbol} 1H: {len(df)} barras {df['dt'].iloc[0].date()} -> "
          f"{df['dt'].iloc[-1].date()} | vol 1H media "
          f"{(abs(df['f1']).mean()):.1f} bps")
    print("# barra de tradability standalone ~30 bps/trade (round trip realistic);")
    print("# por debajo solo vale como filtro de un motor 4H.")

    screen_hour_of_day(df)
    screen_weekday(df)
    screen_sweep(df)
    if not args.skip_funding:
        screen_funding(df, args.symbol)


if __name__ == "__main__":
    main()
