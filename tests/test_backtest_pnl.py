"""Tests del pairing de P&L por trade (fix auditoria 2026-07-02, hallazgo B3).

_compute_trade_pnl (average cost basis) debe:
- coincidir con el pairing clasico en el caso todo-in/todo-out,
- manejar ventas parciales con cantidades arbitrarias (Swing Allocator),
- ignorar ventas sin posicion.
"""
from datetime import datetime, timezone
from decimal import Decimal

from core.backtest import BacktestClient, BacktestEngine, BacktestTrade
from data.market_data import OHLCVBar


def _t(side: str, price: str, qty: str, fee: str = "0") -> BacktestTrade:
    return BacktestTrade(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        symbol="BTC-USDT", side=side,
        price=Decimal(price), quantity=Decimal(qty), fee=Decimal(fee),
    )


def _bar(hour: int, open_: str, close: str) -> OHLCVBar:
    ts = int(datetime(2024, 1, 1, hour, tzinfo=timezone.utc).timestamp() * 1000)
    return OHLCVBar(
        timestamp=ts,
        open=Decimal(open_),
        high=Decimal(max(open_, close)),
        low=Decimal(min(open_, close)),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def test_simetrico_coincide_con_legacy():
    trades = [_t("buy", "100", "1", "0.10"), _t("sell", "110", "1", "0.11")]
    acb = BacktestEngine._compute_trade_pnl(trades)
    legacy = BacktestEngine._compute_trade_pnl_legacy_fifo(trades)
    assert len(acb) == len(legacy) == 1
    # ACB: 1*(110 - 100.10) - 0.11 = 9.79 | legacy: (110-100)*1 - 0.11 - 0.10 = 9.79
    assert acb[0].pnl == legacy[0].pnl == Decimal("9.79")


def test_ventas_parciales_cierran_dos_trades():
    trades = [
        _t("buy", "100", "2", "0.20"),          # basis = 100.10
        _t("sell", "110", "1", "0.11"),
        _t("sell", "90", "1", "0.09"),
    ]
    acb = BacktestEngine._compute_trade_pnl(trades)
    assert len(acb) == 2
    assert acb[0].pnl == Decimal("9.79")        # 1*(110-100.10) - 0.11
    assert acb[1].pnl == Decimal("-10.19")      # 1*(90-100.10) - 0.09
    # el pairing legacy consumia el lote entero en la primera venta y perdia la segunda
    legacy = BacktestEngine._compute_trade_pnl_legacy_fifo(trades)
    assert len(legacy) == 1


def test_coste_medio_pondera_compras():
    trades = [
        _t("buy", "100", "1"),
        _t("buy", "200", "1"),                  # basis = 150
        _t("sell", "180", "2"),
    ]
    acb = BacktestEngine._compute_trade_pnl(trades)
    assert len(acb) == 1
    assert acb[0].pnl == Decimal("60.00")       # 2*(180-150)


def test_venta_sin_posicion_se_ignora():
    trades = [_t("sell", "100", "1")]
    assert BacktestEngine._compute_trade_pnl(trades) == []


def test_venta_mayor_que_posicion_se_recorta():
    trades = [_t("buy", "100", "1"), _t("sell", "110", "5", "0.50")]
    acb = BacktestEngine._compute_trade_pnl(trades)
    assert len(acb) == 1
    assert acb[0].quantity == Decimal("1")
    assert acb[0].fee == Decimal("0.10")
    assert acb[0].pnl == Decimal("9.90")


def test_selector_legacy_sigue_disponible():
    from unittest.mock import Mock

    engine = BacktestEngine(Mock(), Mock(), trade_pnl_method="legacy_fifo")
    assert engine._trade_pnl_method == "legacy_fifo"


def test_market_fill_default_usa_close_actual():
    client = BacktestClient(
        "BTC-USDT",
        [_bar(0, "100", "110"), _bar(1, "120", "130")],
        initial_balance=Decimal("1000"),
        slippage_bps=0,
    )
    client.advance(0)
    order = client.place_order("BTC-USDT", "buy", "market", Decimal("1"))
    assert order.filled_price == Decimal("110")


def test_market_fill_next_open_usa_open_siguiente():
    client = BacktestClient(
        "BTC-USDT",
        [_bar(0, "100", "110"), _bar(1, "120", "130")],
        initial_balance=Decimal("1000"),
        slippage_bps=0,
        fill_next_open=True,
    )
    client.advance(0)
    order = client.place_order("BTC-USDT", "buy", "market", Decimal("1"))
    assert order.status == "open"
    assert order.filled_price is None
    assert client.current_time() == datetime(2024, 1, 1, 0, tzinfo=timezone.utc)
    assert client.get_balance() == {"USDT": Decimal("1000")}

    fills = client.advance(1)

    assert len(fills) == 1
    assert fills[0].filled_price == Decimal("120")
    assert fills[0].timestamp == datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
