"""Public-source adapters with atomic, hashed, append-only snapshots.

All network access is read-only and uses urllib.  Provider failures are recorded
in the manifest instead of being silently replaced.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .core import canonical_json, sha256_bytes
from .models import HalvingRecord, PriceBar, SourceSnapshot


USER_AGENT = "MatiTradingBot-BTCCycleAudit/1.0 (research-only)"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_json(url: str, *, timeout: int = 30) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(url: str, *, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain, application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8").strip()


def blockstream_halving(height: int, *, cache_dir: Path) -> HalvingRecord:
    retrieved = now_utc()
    cache_dir.mkdir(parents=True, exist_ok=True)
    hash_path = cache_dir / f"block_{height}_hash.json"
    if hash_path.exists():
        payload = json.loads(hash_path.read_text(encoding="utf-8"))
    else:
        block_hash = get_text(f"https://blockstream.info/api/block-height/{height}")
        payload = {"height": height, "hash": block_hash, "retrieved_at": retrieved, "url": f"https://blockstream.info/api/block/{block_hash}"}
        hash_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    block_path = cache_dir / f"block_{height}.json"
    if block_path.exists():
        block = json.loads(block_path.read_text(encoding="utf-8"))
    else:
        block = get_json(f"https://blockstream.info/api/block/{payload['hash']}")
        block_path.write_text(json.dumps(block, indent=2, sort_keys=True), encoding="utf-8")
    timestamp = datetime.fromtimestamp(int(block["timestamp"]), timezone.utc).isoformat().replace("+00:00", "Z")
    digest = sha256_bytes(canonical_json({"hash": payload["hash"], "block": block}))
    return HalvingRecord(height, str(payload["hash"]), timestamp, "blockstream_esplora", ("blockstream_block_api",), retrieved, digest)


def estimate_next_halving(*, tip_height: int, last_halving_height: int, last_halving_time: str, interval_blocks: int = 210_000) -> dict:
    elapsed_seconds = max((datetime.now(timezone.utc) - datetime.fromisoformat(last_halving_time.replace("Z", "+00:00"))).total_seconds(), 1)
    blocks = max(tip_height - last_halving_height, 1)
    seconds_per_block = elapsed_seconds / blocks
    remaining = max(interval_blocks - blocks, 0)
    estimated = datetime.now(timezone.utc).timestamp() + remaining * seconds_per_block
    return {"status": "ESTIMATED", "estimated_height": last_halving_height + interval_blocks, "estimated_timestamp_utc": datetime.fromtimestamp(estimated, timezone.utc).isoformat().replace("+00:00", "Z"), "seconds_per_block": seconds_per_block, "tip_height": tip_height, "as_of": now_utc()}


def _bar(source: str, timestamp: int | str, values: list, *, volume: str | None = None, interval: str = "1d") -> PriceBar:
    ts = datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat().replace("+00:00", "Z") if str(timestamp).isdigit() else str(timestamp)
    return PriceBar(source, ts, str(values[0]), str(values[1]), str(values[2]), str(values[3]), volume, interval, now_utc())


def fetch_coinbase_daily(start: int, end: int) -> list[PriceBar]:
    result: list[PriceBar] = []
    cursor = start
    chunk = 300 * 86400
    while cursor < end:
        chunk_end = min(cursor + chunk, end)
        url = "https://api.exchange.coinbase.com/products/BTC-USD/candles?" + urllib.parse.urlencode({"start": cursor, "end": chunk_end, "granularity": 86400})
        rows = get_json(url)
        result.extend(_bar("coinbase", row[0], [row[3], row[2], row[1], row[4]], volume=str(row[5])) for row in rows)
        cursor = chunk_end + 1
    return result


def fetch_bitstamp_daily(start: int, end: int) -> list[PriceBar]:
    result: list[PriceBar] = []
    cursor = start
    while cursor < end:
        url = "https://www.bitstamp.net/api/v2/ohlc/btcusd/?" + urllib.parse.urlencode({"step": 86400, "start": cursor, "limit": 1000})
        rows = get_json(url)["data"]["ohlc"]
        result.extend(_bar("bitstamp", row["timestamp"], [row["open"], row["high"], row["low"], row["close"]], volume=row.get("volume")) for row in rows if cursor <= int(row["timestamp"]) <= end)
        if not rows:
            break
        newest = max(int(row["timestamp"]) for row in rows)
        if newest <= cursor:
            break
        cursor = newest + 86400
    return result


def fetch_kraken_daily(start: int, end: int) -> list[PriceBar]:
    url = "https://api.kraken.com/0/public/OHLC?" + urllib.parse.urlencode({"pair": "XBTUSD", "interval": 1440, "since": start})
    payload = get_json(url)
    result = payload["result"]
    rows = next(value for key, value in result.items() if key != "last")
    return [_bar("kraken", row[0], [row[1], row[2], row[3], row[4]], volume=row[6]) for row in rows if int(row[0]) <= end]


def fetch_source(name: str, start: int, end: int) -> tuple[list[PriceBar], SourceSnapshot]:
    fetchers: dict[str, Callable[[int, int], list[PriceBar]]] = {"coinbase": fetch_coinbase_daily, "bitstamp": fetch_bitstamp_daily, "kraken": fetch_kraken_daily}
    retrieved = now_utc()
    try:
        rows = fetchers[name](start, end)
        rows = sorted(rows, key=lambda row: row.timestamp_utc)
        digest = sha256_bytes(canonical_json([row.__dict__ for row in rows]))
        return rows, SourceSnapshot(name, "1d", rows[0].timestamp_utc if rows else None, rows[-1].timestamp_utc if rows else None, len(rows), digest, retrieved, "OK")
    except Exception as exc:
        return [], SourceSnapshot(name, "1d", None, None, 0, "", retrieved, "FAILED", (type(exc).__name__ + ":" + str(exc),))


def write_source_snapshot(root: Path, rows: list[PriceBar], snapshot: SourceSnapshot) -> Path:
    """Write a new version; never overwrite a prior content hash."""
    target = root / snapshot.source / f"{snapshot.dataset_hash}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(json.dumps({"snapshot": snapshot.__dict__, "rows": [row.__dict__ for row in rows]}, indent=2, sort_keys=True), encoding="utf-8")
    return target
