"""Tests para config/settings.py"""
import os
from decimal import Decimal

import pytest

from config.settings import load_settings


def _patch_env(monkeypatch, overrides: dict):
    defaults = {
        "TRADING_MODE": "paper",
        "OKX_SANDBOX": "true",
        "TRADING_PAIRS": "BTC-USDT,ETH-USDT",
        "MAX_PORTFOLIO_RISK_PCT": "2.0",
        "MAX_OPEN_POSITIONS": "10",
        "DAILY_LOSS_LIMIT_PCT": "5.0",
        "FISCAL_YEAR": "2025",
        "COST_BASIS_METHOD": "FIFO",
        "SIGNAL_SOURCE": "none",
        "WEBHOOK_PORT": "8080",
    }
    for key, value in {**defaults, **overrides}.items():
        monkeypatch.setenv(key, value)


def test_paper_mode_loads_without_credentials(monkeypatch):
    _patch_env(monkeypatch, {})
    s = load_settings()
    assert s.is_paper
    assert not s.is_live


def test_trading_pairs_parsed_correctly(monkeypatch):
    _patch_env(monkeypatch, {"TRADING_PAIRS": "BTC-USDT, eth-usdt , SOL-USDT"})
    s = load_settings()
    assert s.trading_pairs == ["BTC-USDT", "ETH-USDT", "SOL-USDT"]


def test_decimal_precision(monkeypatch):
    _patch_env(monkeypatch, {"MAX_PORTFOLIO_RISK_PCT": "1.5"})
    s = load_settings()
    assert s.max_portfolio_risk_pct == Decimal("1.5")
    assert isinstance(s.max_portfolio_risk_pct, Decimal)


def test_live_mode_requires_credentials(monkeypatch):
    _patch_env(monkeypatch, {"TRADING_MODE": "live", "OKX_API_KEY": "", "OKX_SECRET_KEY": "", "OKX_PASSPHRASE": ""})
    with pytest.raises(EnvironmentError, match="OKX_API_KEY"):
        load_settings()


def test_live_mode_with_credentials(monkeypatch):
    _patch_env(monkeypatch, {
        "TRADING_MODE": "live",
        "OKX_API_KEY": "key",
        "OKX_SECRET_KEY": "secret",
        "OKX_PASSPHRASE": "pass",
    })
    s = load_settings()
    assert s.is_live


def test_invalid_trading_mode(monkeypatch):
    _patch_env(monkeypatch, {"TRADING_MODE": "manual"})
    with pytest.raises(EnvironmentError, match="TRADING_MODE"):
        load_settings()


def test_invalid_cost_method(monkeypatch):
    _patch_env(monkeypatch, {"COST_BASIS_METHOD": "LIFO"})
    with pytest.raises(EnvironmentError, match="COST_BASIS_METHOD"):
        load_settings()


def test_settings_are_immutable(monkeypatch):
    _patch_env(monkeypatch, {})
    s = load_settings()
    with pytest.raises(Exception):
        s.trading_mode = "live"  # type: ignore[misc]
