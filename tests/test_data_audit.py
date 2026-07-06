from __future__ import annotations

from tools import data_audit as da


def _row(ts_ms, o=100, h=110, l=90, c=105, v=1):
    return [ts_ms, str(o), str(h), str(l), str(c), str(v)]


def _meta(rows, complete=True):
    return {"symbol": "BTC-USDT", "bar": "1H", "complete": complete, "bars": rows}


HOUR = 3_600_000


def test_audit_missing_cache(monkeypatch):
    monkeypatch.setattr(da.ohlcv_cache, "load_meta", lambda *_a, **_k: None)
    res = da.audit_cache()
    assert res["exists"] is False


def test_audit_clean_contiguous_cache(monkeypatch):
    rows = [_row(i * HOUR) for i in range(1, 50)]
    monkeypatch.setattr(da.ohlcv_cache, "load_meta", lambda *_a, **_k: _meta(rows))
    res = da.audit_cache()
    assert res["exists"] and res["clean"]
    assert res["n_gaps"] == 0 and res["n_duplicates"] == 0
    assert res["out_of_order_pairs"] == 0


def test_audit_detects_duplicates(monkeypatch):
    rows = [_row(1 * HOUR), _row(2 * HOUR), _row(2 * HOUR), _row(3 * HOUR)]
    monkeypatch.setattr(da.ohlcv_cache, "load_meta", lambda *_a, **_k: _meta(rows))
    res = da.audit_cache()
    assert res["n_duplicates"] == 1
    assert res["clean"] is False


def test_audit_detects_high_below_low_and_hard_jump(monkeypatch):
    rows = [
        _row(1 * HOUR, c=100),
        _row(2 * HOUR, h=50, l=90),          # high<low
        _row(3 * HOUR, c=100),
        _row(4 * HOUR, c=200),               # +100% salto duro vs prev close
    ]
    monkeypatch.setattr(da.ohlcv_cache, "load_meta", lambda *_a, **_k: _meta(rows))
    res = da.audit_cache()
    kinds = {o["kind"] for o in res["outlier_samples"]}
    assert "high<low" in kinds
    assert "hard-jump" in kinds
    assert res["n_hard_outliers"] >= 2
    assert res["clean"] is False


def test_format_report_runs(monkeypatch):
    rows = [_row(i * HOUR) for i in range(1, 10)]
    monkeypatch.setattr(da.ohlcv_cache, "load_meta", lambda *_a, **_k: _meta(rows))
    txt = da.format_report(da.audit_cache())
    assert "Data Audit" in txt and "LIMPIO" in txt
