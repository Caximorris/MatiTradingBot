"""Tests para reporting/fiscal_report.py — FIFO, IRPF 2026, sin Excel real."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from reporting.fiscal_report import (
    FIFOCalculator,
    GainLossRecord,
    PurchaseLot,
    calculate_irpf_tax,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _make_trade(trade_id, symbol, side, quantity, price, fee=Decimal("0"), timestamp=None):
    """Mock de Trade para tests FIFO — solo necesitamos los campos relevantes."""
    from unittest.mock import MagicMock
    t = MagicMock()
    t.id = trade_id
    t.symbol = symbol
    t.side = side
    t.quantity = Decimal(str(quantity))
    t.price = Decimal(str(price))
    t.fee = Decimal(str(fee))
    t.timestamp = timestamp or _utc(2025, 1, trade_id)
    return t


RATE = Decimal("1.0")  # 1 USDT = 1 EUR para simplificar los asserts


# ---------------------------------------------------------------------------
# Tests FIFOCalculator — lote único
# ---------------------------------------------------------------------------

def test_fifo_single_lot_gain():
    """Compra 1 BTC a 60000, vende a 65000 → ganancia 5000 EUR."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "60000", fee="0"))
    calc.process_trade(_make_trade(2, "BTC-USDT", "sell", "1", "65000", fee="0"))

    assert len(calc.gain_loss_records) == 1
    r = calc.gain_loss_records[0]
    assert r.net_gain_eur == Decimal("5000.00")
    assert r.quantity == Decimal("1")


def test_fifo_single_lot_loss():
    """Compra 1 BTC a 65000, vende a 60000 → pérdida 5000 EUR."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "65000", fee="0"))
    calc.process_trade(_make_trade(2, "BTC-USDT", "sell", "1", "60000", fee="0"))

    r = calc.gain_loss_records[0]
    assert r.net_gain_eur == Decimal("-5000.00")


def test_fifo_fees_reduce_net_gain():
    """Comisiones se descuentan del resultado neto."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    # Compra: 1 BTC @ 60000 + 60 EUR comisión
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "60000", fee="60"))
    # Venta: 1 BTC @ 65000 + 65 EUR comisión
    calc.process_trade(_make_trade(2, "BTC-USDT", "sell", "1", "65000", fee="65"))

    r = calc.gain_loss_records[0]
    # Ganancia bruta 5000 - comisiones (60 + 65) = 4875
    assert r.net_gain_eur == Decimal("4875.00")
    assert r.total_fees_eur == Decimal("125.00")


# ---------------------------------------------------------------------------
# Tests FIFOCalculator — múltiples lotes (FIFO real)
# ---------------------------------------------------------------------------

def test_fifo_consumes_oldest_lot_first():
    """Venta consume el lote más antiguo (FIFO, no LIFO)."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    # Lote 1: 1 BTC @ 50000 (antiguo)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "50000",
                                   timestamp=_utc(2025, 1, 1)))
    # Lote 2: 1 BTC @ 70000 (reciente)
    calc.process_trade(_make_trade(2, "BTC-USDT", "buy", "1", "70000",
                                   timestamp=_utc(2025, 6, 1)))
    # Venta: 1 BTC @ 65000 — debe usar el lote de 50000
    calc.process_trade(_make_trade(3, "BTC-USDT", "sell", "1", "65000",
                                   timestamp=_utc(2025, 9, 1)))

    assert len(calc.gain_loss_records) == 1
    r = calc.gain_loss_records[0]
    assert r.buy_price_eur == Decimal("50000")
    assert r.net_gain_eur == Decimal("15000.00")


def test_fifo_sell_spanning_two_lots():
    """Venta de 2 BTC consume dos lotes con precios distintos."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "50000"))
    calc.process_trade(_make_trade(2, "BTC-USDT", "buy", "1", "60000"))
    calc.process_trade(_make_trade(3, "BTC-USDT", "sell", "2", "70000"))

    assert len(calc.gain_loss_records) == 2
    nets = sorted(r.net_gain_eur for r in calc.gain_loss_records)
    assert nets == [Decimal("10000.00"), Decimal("20000.00")]


def test_fifo_partial_lot_consumption():
    """Venta parcial deja el resto del lote disponible para la siguiente venta."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "50000"))
    # Vende 0.5 BTC → consume la mitad del lote
    calc.process_trade(_make_trade(2, "BTC-USDT", "sell", "0.5", "60000"))
    # Vende los 0.5 restantes
    calc.process_trade(_make_trade(3, "BTC-USDT", "sell", "0.5", "70000"))

    assert len(calc.gain_loss_records) == 2
    gains = [r.net_gain_eur for r in calc.gain_loss_records]
    # Primera venta: (60000-50000)*0.5 = 5000
    # Segunda venta: (70000-50000)*0.5 = 10000
    assert Decimal("5000.00") in gains
    assert Decimal("10000.00") in gains


def test_fifo_multiple_symbols_independent():
    """Los lotes de BTC y ETH son completamente independientes."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "50000"))
    calc.process_trade(_make_trade(2, "ETH-USDT", "buy", "10", "3000"))
    calc.process_trade(_make_trade(3, "BTC-USDT", "sell", "1", "55000"))
    calc.process_trade(_make_trade(4, "ETH-USDT", "sell", "10", "2500"))

    btc = [r for r in calc.gain_loss_records if r.symbol == "BTC-USDT"]
    eth = [r for r in calc.gain_loss_records if r.symbol == "ETH-USDT"]

    assert len(btc) == 1 and btc[0].net_gain_eur == Decimal("5000.00")
    assert len(eth) == 1 and eth[0].net_gain_eur == Decimal("-5000.00")


def test_fifo_sell_without_lots_is_recorded_as_unmatched():
    """Venta sin compra previa se registra en unmatched_sells, no crashea."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    calc.process_trade(_make_trade(1, "BTC-USDT", "sell", "1", "65000"))

    assert len(calc.gain_loss_records) == 0
    assert len(calc.unmatched_sells) == 1


def test_fifo_usd_eur_rate_applied():
    """La tasa USD/EUR se aplica correctamente a todos los precios."""
    rate = Decimal("0.92")
    calc = FIFOCalculator(usd_eur_rate=rate)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "10000"))
    calc.process_trade(_make_trade(2, "BTC-USDT", "sell", "1", "11000"))

    r = calc.gain_loss_records[0]
    # buy_price = 10000 * 0.92 = 9200, sell_price = 11000 * 0.92 = 10120
    # ganancia = (10120 - 9200) * 1 = 920
    assert r.buy_price_eur == Decimal("9200.00")
    assert r.sell_price_eur == Decimal("10120.00")
    assert r.net_gain_eur == Decimal("920.00")


# ---------------------------------------------------------------------------
# Tests calculate_irpf_tax
# ---------------------------------------------------------------------------

def test_irpf_zero_on_no_gain():
    assert calculate_irpf_tax(Decimal("0")) == Decimal("0")


def test_irpf_zero_on_loss():
    assert calculate_irpf_tax(Decimal("-1000")) == Decimal("0")


def test_irpf_first_bracket_only():
    """3000€ de ganancia → 3000 * 19% = 570€."""
    tax = calculate_irpf_tax(Decimal("3000"))
    assert tax == Decimal("570.00")


def test_irpf_exactly_at_first_bracket_limit():
    """6000€ → 6000 * 19% = 1140€."""
    tax = calculate_irpf_tax(Decimal("6000"))
    assert tax == Decimal("1140.00")


def test_irpf_crosses_first_bracket():
    """10000€ → 6000*19% + 4000*21% = 1140 + 840 = 1980€."""
    tax = calculate_irpf_tax(Decimal("10000"))
    assert tax == Decimal("1980.00")


def test_irpf_crosses_second_bracket():
    """60000€ → 6000*19% + 44000*21% + 10000*23%."""
    expected = (
        Decimal("6000") * Decimal("0.19")
        + Decimal("44000") * Decimal("0.21")
        + Decimal("10000") * Decimal("0.23")
    )
    tax = calculate_irpf_tax(Decimal("60000"))
    assert tax == expected.quantize(Decimal("0.01"))


def test_irpf_top_bracket():
    """Ganancia muy alta incluye tramo del 28%."""
    tax = calculate_irpf_tax(Decimal("300000"))
    # 6000*19% + 44000*21% + 150000*23% + 100000*28%
    expected = (
        Decimal("6000") * Decimal("0.19")
        + Decimal("44000") * Decimal("0.21")
        + Decimal("150000") * Decimal("0.23")
        + Decimal("100000") * Decimal("0.28")
    )
    assert tax == expected.quantize(Decimal("0.01"))


def test_irpf_progressive_not_flat():
    """El tipo efectivo es menor que el tipo marginal del tramo más alto."""
    gain = Decimal("100000")
    tax = calculate_irpf_tax(gain)
    effective_rate = tax / gain
    # El tipo efectivo debe ser menor que 23% (tipo marginal del tramo)
    assert effective_rate < Decimal("0.23")


# ---------------------------------------------------------------------------
# Tests integración: FIFO + IRPF
# ---------------------------------------------------------------------------

def test_net_gain_feeds_irpf():
    """Ganancia neta calculada por FIFO entra en la función IRPF correctamente."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "50000"))
    calc.process_trade(_make_trade(2, "BTC-USDT", "sell", "1", "56000"))

    net = sum((r.net_gain_eur for r in calc.gain_loss_records), Decimal("0"))
    tax = calculate_irpf_tax(net)

    # 6000€ ganancia → 6000 * 19% = 1140€
    assert net == Decimal("6000.00")
    assert tax == Decimal("1140.00")


def test_losses_offset_gains():
    """Pérdidas de un activo compensan ganancias de otro en el resumen."""
    calc = FIFOCalculator(usd_eur_rate=RATE)
    # BTC: +10000
    calc.process_trade(_make_trade(1, "BTC-USDT", "buy", "1", "50000"))
    calc.process_trade(_make_trade(2, "BTC-USDT", "sell", "1", "60000"))
    # ETH: -4000
    calc.process_trade(_make_trade(3, "ETH-USDT", "buy", "10", "2000"))
    calc.process_trade(_make_trade(4, "ETH-USDT", "sell", "10", "1600"))

    net = sum((r.net_gain_eur for r in calc.gain_loss_records), Decimal("0"))
    assert net == Decimal("6000.00")  # 10000 - 4000
    tax = calculate_irpf_tax(net)
    assert tax == Decimal("1140.00")
