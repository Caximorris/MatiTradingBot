from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import tools.funding_refresh as fr
from strategies import swing_funding_overlay as ov


def _write_cache(path, rows):
    json.dump([[ts, rate] for ts, rate in rows], open(path, "w", encoding="utf-8"))


def test_refresh_merges_new_settlements_and_dedups(tmp_path, monkeypatch):
    cache = tmp_path / "funding_bybit_BTCUSDT.json"
    _write_cache(cache, [(1000, 0.01), (2000, 0.02)])
    monkeypatch.setattr(fr, "_cache_path", lambda sym, source="bybit": cache)

    # Bybit devuelve descendente; una sola pagina que solapa lo conocido (3000 nuevo, 2000 ya esta).
    pages = iter([[(3000, 0.03), (2000, 0.02)]])
    monkeypatch.setattr(fr, "_fetch_page", lambda sym, end, source="bybit": next(pages, []))

    r = fr.refresh("BTCUSDT")

    assert r["added"] == 1
    assert r["total"] == 3
    rows = json.load(open(cache, encoding="utf-8"))
    assert [ts for ts, _ in rows] == [1000, 2000, 3000]  # ordenado ascendente, sin duplicar 2000


def test_refresh_backfills_when_cache_missing(tmp_path, monkeypatch):
    cache = tmp_path / "funding_bybit_BTCUSDT.json"
    monkeypatch.setattr(fr, "_cache_path", lambda sym, source="bybit": cache)
    pages = iter([[(2000, 0.02), (1000, 0.01)], []])  # segunda pagina vacia -> fin
    monkeypatch.setattr(fr, "_fetch_page", lambda sym, end, source="bybit": next(pages, []))

    r = fr.refresh("BTCUSDT")

    assert r["added"] == 2
    assert r["total"] == 2


def test_okx_refresh_uses_final_settlement_feed_and_venue_cache(tmp_path, monkeypatch):
    cache = tmp_path / "funding_okx_BTC-USDT-SWAP.json"
    monkeypatch.setattr(fr, "_cache_path", lambda sym, source="bybit": cache)
    calls = []
    pages = iter([[(3000, 0.03), (2000, 0.02)], []])

    def fetch(sym, cursor, source="bybit"):
        calls.append((sym, cursor, source))
        return next(pages, [])

    monkeypatch.setattr(fr, "_fetch_page", fetch)

    result = fr.refresh("BTC-USDT", source="okx")

    assert result["source"] == "okx"
    assert result["market"] == "BTC-USDT-SWAP"
    assert calls[0] == ("BTC-USDT", None, "okx")
    assert json.loads(cache.read_text(encoding="utf-8")) == [[2000, 0.02], [3000, 0.03]]


def test_overlay_cache_invalidates_when_file_changes(tmp_path, monkeypatch):
    cache = tmp_path / "funding_bybit_BTCUSDT.json"
    monkeypatch.setattr(ov, "funding_cache_path", lambda sym, source="bybit": cache)
    ov._cached_events.cache_clear()

    # 100 settlements planos + un pico alto al final -> hay evento en accumulation.
    base = [(1_000_000_000_000 + i * 8 * 3600 * 1000, 0.0) for i in range(100)]
    base.append((base[-1][0] + 8 * 3600 * 1000, 0.05))
    _write_cache(cache, base)

    cfg = SimpleNamespace(
        funding_overlay_lookback_settlements=90, funding_low_pctile=0.10,
        funding_high_pctile=0.90, funding_overlay_dedup_days=7, funding_overlay_ttl_days=7,
        funding_overlay_phases="accumulation", funding_overlay_delta=0.05,
    )
    from datetime import datetime, timezone
    now = datetime.fromtimestamp(base[-1][0] / 1000 + 3600, tz=timezone.utc)

    ov.funding_overlay_adjustment("BTCUSDT", now, "accumulation", cfg)
    misses_before = ov._cached_events.cache_info().misses

    # Reescribir el archivo cambia el mtime -> debe recomputar (no servir cache viejo).
    import os
    os.utime(cache, (base[-1][0] / 1000 + 10, base[-1][0] / 1000 + 10))
    ov.funding_overlay_adjustment("BTCUSDT", now, "accumulation", cfg)
    misses_after = ov._cached_events.cache_info().misses

    assert misses_after == misses_before + 1


def test_enabled_overlay_rejects_missing_or_empty_snapshot(tmp_path, monkeypatch):
    cache = tmp_path / "funding_bybit_BTCUSDT.json"
    monkeypatch.setattr(ov, "funding_cache_path", lambda _sym, source="bybit": cache)
    cfg = SimpleNamespace()
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)

    with pytest.raises(ov.FundingOverlayError, match="missing"):
        ov.funding_overlay_adjustment("BTCUSDT", now, "accumulation", cfg)

    _write_cache(cache, [])
    with pytest.raises(ov.FundingOverlayError, match="empty"):
        ov.funding_overlay_adjustment("BTCUSDT", now, "accumulation", cfg)


def test_enabled_overlay_rejects_stale_snapshot(tmp_path, monkeypatch):
    cache = tmp_path / "funding_bybit_BTCUSDT.json"
    monkeypatch.setattr(ov, "funding_cache_path", lambda _sym, source="bybit": cache)
    now = datetime(2024, 1, 3, tzinfo=timezone.utc)
    _write_cache(
        cache,
        [(int((now - timedelta(hours=27)).timestamp() * 1000), 0.01)],
    )

    with pytest.raises(ov.FundingOverlayError, match="stale"):
        ov.funding_overlay_adjustment("BTCUSDT", now, "accumulation", SimpleNamespace())
