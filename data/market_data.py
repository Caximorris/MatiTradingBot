"""Obtención y caché de datos OHLCV desde OKX."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from core.exchange import OKXClient


@dataclass
class OHLCVBar:
    timestamp: int  # Unix ms
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class _CacheEntry:
    bars: list[OHLCVBar]
    fetched_at: float  # time.time()


class MarketDataCache:
    """
    Caché con TTL para datos OHLCV.
    Thread-safe: múltiples estrategias pueden compartir una instancia.
    """

    def __init__(self, client: "OKXClient", ttl_seconds: int = 60) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get_ohlcv(
        self,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> list[OHLCVBar]:
        """
        Retorna velas OHLCV desde la caché o desde OKX si la caché expiró.
        Retorna lista vacía si el exchange no está disponible.
        """
        cache_key = f"{symbol}:{bar}:{limit}"
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and (time.time() - entry.fetched_at) < self._ttl:
                return entry.bars

        bars = self._fetch(symbol, bar, limit)
        if bars:
            with self._lock:
                self._cache[cache_key] = _CacheEntry(bars=bars, fetched_at=time.time())
        return bars

    def _fetch(self, symbol: str, bar: str, limit: int) -> list[OHLCVBar]:
        try:
            raw = self._client.get_ohlcv(symbol, bar=bar, limit=limit)
            return [
                OHLCVBar(
                    timestamp=int(r[0]),
                    open=Decimal(str(r[1])),
                    high=Decimal(str(r[2])),
                    low=Decimal(str(r[3])),
                    close=Decimal(str(r[4])),
                    volume=Decimal(str(r[5])),
                )
                for r in raw
            ]
        except Exception as exc:
            logger.warning("MarketDataCache: error obteniendo OHLCV {}/{}: {}", symbol, bar, exc)
            return []

    def invalidate(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                keys = [k for k in self._cache if k.startswith(symbol)]
                for k in keys:
                    del self._cache[k]
