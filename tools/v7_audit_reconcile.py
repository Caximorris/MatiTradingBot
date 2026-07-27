"""Compare the certified V7 ledger with the independent reference ledger."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.certification import CertifiedEngine  # noqa: E402
from data.market_data import OHLCVBar  # noqa: E402
from strategies.certified_adapters import swing_cycle_core_factory  # noqa: E402
from tools.v7_independent_reference import Spec, load_canonical, run  # noqa: E402

def reconcile(out: Path) -> dict[str, object]:
    cache = ROOT / "data" / "cache" / "BTC-USDT_1H.json"
    bars = load_canonical(cache, datetime(2014, 4, 26, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc))
    reference, curve = run(bars, Spec())
    engine_bars = [OHLCVBar(item.timestamp, item.open, item.high, item.low, item.close, item.volume) for item in bars]
    engine = CertifiedEngine(engine_bars, initial_cash=Decimal("10000"), fee_rate=Decimal(".001"), slippage_bps=Decimal("5"))
    engine.run(swing_cycle_core_factory({}), warmup_bars=6000)
    ledger = engine.execution_ledger
    fields = ("submitted_at", "fill_at", "side", "fill_price", "quantity", "fee", "cash_before", "cash_after", "base_before", "base_after", "equity_after")
    rows = []
    for number, (ref, cert) in enumerate(zip(reference, ledger), 1):
        mapped = {
            "submitted_at": ref["decision_timestamp"], "fill_at": ref["fill_timestamp"], "side": ref["side"],
            "fill_price": ref["fill_price"], "quantity": ref["quantity"], "fee": ref["fee"],
            "cash_before": ref["cash_before"], "cash_after": ref["cash_after"],
            "base_before": ref["btc_before"], "base_after": ref["btc_after"], "equity_after": ref["equity_after"],
        }
        cert_text = {key: cert[key].isoformat() if isinstance(cert[key], datetime) else str(cert[key]) for key in fields}
        differing = [key for key in fields if mapped[key] != cert_text[key]]
        rows.append({"sequence": number, "phase": ref["phase"], "days_since_halving": ref["days_since_halving"],
                     "causal": cert["fill_at"] > cert["submitted_at"],
                     "inside_fill_range": Decimal(ref["fill_low"]) <= Decimal(ref["fill_price"]) <= Decimal(ref["fill_high"]),
                     "affordable": Decimal(ref["cash_after"]) >= 0, "differences": ",".join(differing), **ref, **{f"certified_{key}": cert_text[key] for key in fields}})
    result = {"passed": len(reference) == len(ledger) and all(not row["differences"] for row in rows),
              "operations": len(rows), "final_reference_equity": curve[-1]["equity"],
              "final_certified_equity": str(engine.cash + engine.base_qty * engine_bars[-1].close)}
    out.mkdir(parents=True, exist_ok=True)
    with (out / "operation_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "reconciliation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(reconcile(ROOT / ".v7-operation-audit"), indent=2))
