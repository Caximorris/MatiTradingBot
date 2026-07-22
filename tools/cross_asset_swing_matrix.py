"""Run the frozen same-window BTC/ETH/SOL Swing comparison."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli.runner import _run_backtest  # noqa: E402


OUTPUT = ROOT / "backtests" / "incomplete" / "cross_asset_swing_matrix_fixed.json"
FROM_DT = datetime(2021, 7, 1, tzinfo=UTC)
TO_DT = datetime(2026, 1, 1, tzinfo=UTC)
FROM_DATE = FROM_DT
TO_DATE = TO_DT
BALANCE = Decimal("10000")
TIMEFRAME = "1H"
COST_MODE = "realistic"

RUNS = (
    ("BTC-USDT", "frozen_v6_2", {}),
    (
        "ETH-USDT",
        "phase_free",
        {
            "use_halving": False,
            "use_phase_policy_router": False,
            "use_funding_overlay": False,
        },
    ),
    (
        "ETH-USDT",
        "btc_phase",
        {
            "phase_symbol": "BTC-USDT",
            "use_halving": True,
            "use_phase_policy_router": True,
            "use_funding_overlay": False,
        },
    ),
    (
        "SOL-USDT",
        "phase_free",
        {
            "use_halving": False,
            "use_phase_policy_router": False,
            "use_funding_overlay": False,
        },
    ),
    (
        "SOL-USDT",
        "btc_phase",
        {
            "phase_symbol": "BTC-USDT",
            "use_halving": True,
            "use_phase_policy_router": True,
            "use_funding_overlay": False,
        },
    ),
)


def _number(value: object) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value  # type: ignore[return-value]


def _result_metrics(result: object) -> dict[str, object]:
    """Return the compact, JSON-safe metrics used by the matrix report."""
    return {
        "final_balance": _number(getattr(result, "final_balance")),
        "cagr_pct": _number(getattr(result, "cagr")),
        "max_drawdown_pct": _number(getattr(result, "max_drawdown_pct")),
        "calmar": _number(getattr(result, "calmar")),
        "coin_buy_hold_pct": _number(getattr(result, "buy_hold_pnl_pct")),
        "final_asset_qty": _number(getattr(result, "final_asset_qty", None)),
        "bnh_initial_asset": _number(getattr(result, "bnh_initial_asset", None)),
        "asset_vs_bnh_ratio": _number(getattr(result, "asset_vs_bnh_ratio", None)),
    }


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    rows: list[dict[str, object]] = []
    for symbol, variant, config in RUNS:
        manifests: list[Path] = []
        result = _run_backtest(
            symbol=symbol,
            bar=TIMEFRAME,
            strategy_name="swing",
            initial_balance=float(BALANCE),
            config=config,
            from_dt=FROM_DT,
            to_dt=TO_DT,
            show_progress=False,
            cost_mode=COST_MODE,
            manifest_out=manifests,
        )
        buy_hold_pct = Decimal(str(result.buy_hold_pnl_pct))
        rows.append(
            {
                "symbol": symbol,
                "variant": variant,
                "final_balance": _number(result.final_balance),
                "cagr_pct": _number(result.cagr_pct),
                "max_drawdown_pct": _number(result.max_drawdown_pct),
                "calmar_ratio": _number(result.calmar_ratio),
                "buy_hold_final": str(Decimal("10000") * (Decimal("1") + buy_hold_pct / Decimal("100"))),
                "buy_hold_pnl_pct": _number(result.buy_hold_pnl_pct),
                "final_asset_qty": _number(getattr(result, "final_asset_qty", None)),
                "bnh_initial_asset": _number(getattr(result, "bnh_initial_asset", None)),
                "asset_vs_bnh_ratio": _number(getattr(result, "asset_vs_bnh_ratio", None)),
                "trades": len(result.trades),
                "manifests": [str(path.relative_to(ROOT)) for path in manifests],
            }
        )
    payload = {
        "window": "2021-07-01T00:00:00Z/2026-01-01T00:00:00Z",
        "timeframe": TIMEFRAME,
        "initial_balance": str(BALANCE),
        "costs": COST_MODE,
        "btc_comparator_note": "Frozen v6 policy with funding overlay off because the protected Bybit funding cache is unavailable locally.",
        "runs": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
