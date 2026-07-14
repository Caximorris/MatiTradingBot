from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tools.demo_journal_reconcile import reconcile_demo_journal


STRATEGY = "swing_allocator_demo_btc_usdt"
NOW = datetime(2026, 7, 14, 9, 15, tzinfo=timezone.utc)


def _wallet(path, *, btc: str = "0.032895", cash: str = "8691.55", mirror: bool = True):
    path.write_text(json.dumps({
        "balances": {"BTC": btc, "USDT": cash},
        "updated_at": "2026-07-14T09:14:00+00:00",
        "mirror_of": "okx_demo_trading" if mirror else "unknown",
    }), encoding="utf-8")


def _journal(path, pct: float = 0.58):
    path.write_text(json.dumps({
        "strategy": STRATEGY,
        "symbol": "BTC-USDT",
        "num": 2,
        "timestamp": "2026-07-13T14:38:00+00:00",
        "direction": "SELL",
        "price": 62500.0,
        "qty": 0.01,
        "btc_pct_before": 0.6,
        "btc_pct_target": 0.2,
        "btc_pct_after": pct,
        "portfolio_usdt": 10750.0,
        "signals": ["halving_bear_onset"],
    }) + "\n", encoding="utf-8")


def _run(wallet, journal, *, now=NOW):
    return reconcile_demo_journal(
        strategy=STRATEGY,
        symbol="BTC-USDT",
        wallet_path=wallet,
        journal_path=journal,
        price=Decimal("62557"),
        execution_quote="USDC",
        reason="Correccion manual previa fuera del journal",
        now=now,
    )


def test_appends_distinct_audited_reconcile_event(tmp_path):
    wallet = tmp_path / "paper_state_okx_demo.json"
    journal = tmp_path / "swing_rebalances.jsonl"
    _wallet(wallet)
    _journal(journal)

    result = _run(wallet, journal, now=datetime(2026, 7, 14, 11, 0, tzinfo=timezone.utc))
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]

    assert result.status == "appended"
    assert result.gap_pp > Decimal("15")
    assert len(rows) == 2
    event = rows[-1]
    assert event["direction"] == "RECONCILE"
    assert event["qty"] == 0
    assert event["btc_pct_after"] == event["btc_pct_target"]
    assert event["reconciliation"]["execution_quote"] == "USDC"
    assert event["reconciliation"]["mirror_quote_key"] == "USDT"
    assert event["reconciliation"]["tracked_balances"] == {
        "BTC": "0.032895", "USDT": "8691.55",
    }


def test_same_wallet_snapshot_is_idempotent(tmp_path):
    wallet = tmp_path / "paper_state_okx_demo.json"
    journal = tmp_path / "swing_rebalances.jsonl"
    _wallet(wallet)
    _journal(journal)

    first = _run(wallet, journal)
    second = _run(wallet, journal)

    assert first.status == "appended"
    assert second.status == "already_reconciled"
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 2


def test_later_stale_event_can_be_superseded_again(tmp_path):
    wallet = tmp_path / "paper_state_okx_demo.json"
    journal = tmp_path / "swing_rebalances.jsonl"
    _wallet(wallet)
    _journal(journal)
    _run(wallet, journal)
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "strategy": STRATEGY,
            "timestamp": "2026-07-14T10:00:00+00:00",
            "direction": "SELL",
            "btc_pct_after": 0.58,
        }) + "\n")

    result = _run(wallet, journal, now=datetime(2026, 7, 14, 11, 0, tzinfo=timezone.utc))

    assert result.status == "appended"
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [row["direction"] for row in rows] == [
        "SELL", "RECONCILE", "SELL", "RECONCILE",
    ]


def test_aligned_wallet_does_not_append(tmp_path):
    wallet = tmp_path / "paper_state_okx_demo.json"
    journal = tmp_path / "swing_rebalances.jsonl"
    _wallet(wallet)
    # Current allocation is about 19.1%; 20% is within the anomaly threshold.
    _journal(journal, pct=0.20)

    result = _run(wallet, journal)

    assert result.status == "already_aligned"
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 1


def test_rejects_non_demo_wallet(tmp_path):
    wallet = tmp_path / "paper_state_okx_demo.json"
    journal = tmp_path / "swing_rebalances.jsonl"
    _wallet(wallet, mirror=False)
    _journal(journal)

    with pytest.raises(ValueError, match="mirror_of"):
        _run(wallet, journal)
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 1
