#!/usr/bin/env python
"""Mantiene al dia el cache de funding de Bybit para el overlay del Swing v6.

El overlay (`strategies/swing_funding_overlay.py`) lee un archivo estatico
`data/cache/funding_bybit_{SYM}.json`. En vivo, ese archivo se queda atras y el
overlay nunca dispara. Este tool descarga los settlements nuevos de Bybit y los
fusiona en el cache (dedup por timestamp, escritura atomica). Pensado para cron.

Formato del cache: [[ts_ms, rate], ...] ordenado ascendente por ts (identico al
que produce tools/alpha_screens.fetch_funding).

Uso:
  python tools/funding_refresh.py                      # BTCUSDT
  python tools/funding_refresh.py --symbol ETHUSDT
  python tools/funding_refresh.py --stale-hours 12     # exit!=0 si sigue stale

Bybit BTCUSDT settlea cada 8h -> ~3 filas/dia. Una pagina (200) cubre ~66 dias,
asi que un cron diario casi siempre termina en 1 request.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_API = "https://api.bybit.com/v5/market/funding/history"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_MAX_PAGES = 200  # techo de seguridad; solo se alcanza en backfill desde cero


def _cache_path(symbol: str) -> Path:
    sym = symbol.replace("-", "").upper()
    return ROOT / "data" / "cache" / f"funding_bybit_{sym}.json"


def _load(path: Path) -> dict[int, float]:
    if not path.exists():
        return {}
    rows = json.load(open(path, encoding="utf-8"))
    return {int(ts): float(rate) for ts, rate in rows}


def _fetch_page(symbol: str, end_ms: int | None) -> list[tuple[int, float]]:
    url = f"{_API}?category=linear&symbol={symbol}&limit=200"
    if end_ms is not None:
        url += f"&endTime={end_ms}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if data.get("retCode") not in (0, None):
        raise RuntimeError(f"Bybit retCode={data.get('retCode')}: {data.get('retMsg')}")
    page = data.get("result", {}).get("list", [])
    return [(int(r["fundingRateTimestamp"]), float(r["fundingRate"])) for r in page]


def refresh(symbol: str) -> dict:
    """Descarga settlements nuevos y los fusiona en el cache. Devuelve resumen."""
    sym = symbol.replace("-", "").upper()
    path = _cache_path(sym)
    known = _load(path)
    last_ts = max(known) if known else None

    fetched: dict[int, float] = {}
    end: int | None = None
    for _ in range(_MAX_PAGES):
        page = _fetch_page(sym, end)
        if not page:
            break
        for ts, rate in page:
            fetched.setdefault(ts, rate)
        oldest = min(ts for ts, _ in page)
        # Ya hay cache: en cuanto la pagina alcanza lo conocido, paramos.
        if last_ts is not None and oldest <= last_ts:
            break
        end = oldest - 1
        time.sleep(0.2)

    added = {ts: rate for ts, rate in fetched.items() if ts not in known}
    if added:
        merged = {**known, **added}
        rows = [[ts, merged[ts]] for ts in sorted(merged)]
        tmp = path.with_suffix(".json.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, path)  # atomico: el proceso live nunca lee un archivo a medias
        total = len(rows)
    else:
        total = len(known)

    new_last = max({**known, **added}) if (known or added) else None
    stale_hours = None
    if new_last is not None:
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(new_last / 1000, tz=timezone.utc)
        stale_hours = age.total_seconds() / 3600.0

    return {
        "symbol": sym,
        "added": len(added),
        "total": total,
        "last_settlement": (
            datetime.fromtimestamp(new_last / 1000, tz=timezone.utc).isoformat()
            if new_last is not None else None
        ),
        "stale_hours": stale_hours,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--stale-hours", type=float, default=None,
                   help="Si tras el refresh el ultimo settlement es mas viejo que esto, exit!=0.")
    args = p.parse_args()

    try:
        r = refresh(args.symbol)
    except Exception as exc:  # red caida, API 5xx, etc.: el cron debe alertar
        print(f"funding_refresh ERROR {args.symbol}: {type(exc).__name__}: {exc}")
        return 2

    sh = f"{r['stale_hours']:.1f}" if r["stale_hours"] is not None else "n/a"
    print(f"funding_refresh {r['symbol']}: +{r['added']} nuevos, total {r['total']}, "
          f"ultimo {r['last_settlement']} (stale {sh}h)")

    if args.stale_hours is not None:
        if r["stale_hours"] is None:
            print("funding_refresh STALE: sin datos en cache")
            return 3
        if r["stale_hours"] > args.stale_hours:
            print(f"funding_refresh STALE: {r['stale_hours']:.1f}h > {args.stale_hours}h umbral")
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
