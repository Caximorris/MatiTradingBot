"""Point-in-time OKX EEA BTC-USD index prices for V8 bootstrap decisions."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from .adapter import DOMAIN, SafetyError
from .bootstrap import IndexPriceSample

SOURCE = "okx_eea_btc_usd_index"
INDEX_ID = "BTC-USD"
REFERENCE_WINDOW = timedelta(hours=6)


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _default_http_get(path: str) -> dict[str, Any]:
    if not path.startswith("/api/v5/market/history-index-candles?"):
        raise SafetyError("index history path is outside the allowlist")
    request = urllib.request.Request(
        f"{DOMAIN}{path}",
        headers={"User-Agent": "MatiTradingBot/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except Exception as exc:
        raise SafetyError("OKX EEA index history request failed") from exc
    if not isinstance(payload, dict):
        raise SafetyError("OKX EEA index history response is malformed")
    return payload


class OKXIndexPriceSource:
    def __init__(
        self,
        *,
        market_api: Any,
        http_get: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.market_api = market_api
        self.http_get = http_get or _default_http_get

    @staticmethod
    def _rows(payload: dict[str, Any], label: str) -> list[list[Any]]:
        if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
            raise SafetyError(f"{label} returned an OKX error or malformed rows")
        return payload["data"]

    def reference_after(
        self,
        transition_at: datetime,
        *,
        retrieved_at: datetime,
    ) -> IndexPriceSample:
        if transition_at.tzinfo is None or retrieved_at.tzinfo is None:
            raise SafetyError("index reference timestamps must be timezone-aware")
        transition = transition_at.astimezone(UTC)
        query = urllib.parse.urlencode({
            "instId": INDEX_ID,
            "bar": "1H",
            "limit": "100",
            "after": str(int((transition + REFERENCE_WINDOW).timestamp() * 1000)),
            "before": str(int(transition.timestamp() * 1000)),
        })
        rows = self._rows(
            self.http_get(f"/api/v5/market/history-index-candles?{query}"),
            "BTC-USD index history",
        )
        valid: list[tuple[datetime, list[Any]]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                raise SafetyError("BTC-USD index history row is malformed")
            timestamp = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
            if timestamp > transition and str(row[5]) == "1":
                valid.append((timestamp, row))
        if not valid:
            raise SafetyError("no confirmed BTC-USD index price exists after transition")
        timestamp, row = min(valid, key=lambda item: item[0])
        price = Decimal(str(row[1]))
        if price <= 0:
            raise SafetyError("BTC-USD index reference price is nonpositive")
        return IndexPriceSample(
            SOURCE, INDEX_ID, timestamp, price, retrieved_at.astimezone(UTC),
            _hash({"endpoint": "history-index-candles", "row": row}),
        )

    def current(
        self,
        *,
        verified_server_time: datetime,
        maximum_age_seconds: Decimal = Decimal("5"),
    ) -> IndexPriceSample:
        if verified_server_time.tzinfo is None:
            raise SafetyError("verified OKX server time must be timezone-aware")
        payload = self.market_api.get_index_tickers(instId=INDEX_ID)
        rows = self._rows(payload, "current BTC-USD index ticker")
        if len(rows) != 1:
            raise SafetyError("current BTC-USD index ticker is ambiguous")
        row = rows[0]
        if row.get("instId") != INDEX_ID or row.get("idxPx") in (None, "") or row.get("ts") in (None, ""):
            raise SafetyError("current BTC-USD index ticker fields are incomplete")
        timestamp = datetime.fromtimestamp(int(row["ts"]) / 1000, UTC)
        retrieved = verified_server_time.astimezone(UTC)
        age = Decimal(str((retrieved - timestamp).total_seconds()))
        if age < Decimal("-2") or age > maximum_age_seconds:
            raise SafetyError("current BTC-USD index ticker is stale or future-dated")
        price = Decimal(str(row["idxPx"]))
        if price <= 0:
            raise SafetyError("current BTC-USD index price is nonpositive")
        return IndexPriceSample(
            SOURCE, INDEX_ID, timestamp, price, retrieved,
            _hash({"endpoint": "index-tickers", "row": row}),
        )
