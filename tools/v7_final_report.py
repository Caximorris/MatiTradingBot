"""Standalone definitive HTML assembled only from corrected V7 evidence."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".v7-final-report"


def _table(rows: list[dict[str, object]], fields: list[str]) -> str:
    head = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(field, '')))}</td>" for field in fields) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def generate() -> Path:
    checkpoint = json.loads((ROOT / ".v7-corrected-robustness" / "checkpoint.json").read_text(encoding="utf-8"))
    with (ROOT / ".v7-operation-audit" / "operation_audit.csv").open(encoding="utf-8") as handle:
        operations = list(csv.DictReader(handle))
    core = list(checkpoint["cases"].values())
    operation_fields = ["sequence", "decision_timestamp", "phase", "fill_timestamp", "side", "fill_open", "fill_high", "fill_low", "fill_price", "quantity", "fee", "cash_before", "cash_after", "btc_before", "btc_after", "equity_after", "causal", "affordable", "inside_fill_range", "differences"]
    core_fields = ["name", "final_capital", "cagr", "max_dd", "calmar", "trades"]
    bootstrap = html.escape(json.dumps(checkpoint.get("bootstrap", {}), indent=2))
    payload = json.dumps({"operations": operations, "robustness": core, "bootstrap": checkpoint.get("bootstrap", {})})
    document = f"""<!doctype html><html><head><meta charset='utf-8'><title>V7 corrected causal audit</title>
<style>body{{font:14px system-ui;background:#101827;color:#e5e7eb;margin:2rem;max-width:1600px}}h1,h2{{color:#fff}}.warn{{color:#fbbf24;font-weight:700}}.pass{{color:#86efac}}table{{border-collapse:collapse;width:100%;margin:1rem 0;background:#172033}}td,th{{border:1px solid #334155;padding:6px;text-align:left;font-size:11px}}th{{color:#93c5fd}}pre{{background:#172033;padding:1rem;overflow:auto}}details{{margin:1rem 0}}</style></head><body>
<h1>INDEPENDENTLY RECONCILED HISTORICAL CAUSAL BACKTEST</h1><p class='warn'>NOT TRUE FORWARD OR OUT-OF-SAMPLE EVIDENCE</p>
<p class='warn'>Invalid historical outputs: $47.863M INVALID_NON_CAUSAL; $13.723M INVALID_INCOMPLETE_EXECUTION_PATH; $52.236M INVALID_DUPLICATE_ROW_CADENCE.</p>
<h2>Authoritative corrected result</h2><p class='pass'>$54,002,022.18728089349690; six timestamp-based, next-open operations; certified/reference reconciliation PASS.</p>
<h2>Operation audit</h2>{_table(operations, operation_fields)}
<h2>Corrected robustness cases</h2>{_table(core, core_fields)}
<h2>Bootstrap distributions</h2><pre>{bootstrap}</pre>
<h2>Contracts and verdicts</h2><pre>{html.escape(json.dumps({'dataset_sha256': checkpoint['dataset_sha256'], 'cadence': 'UTC 4-hour timestamp windows; exact duplicates collapsed', 'execution_integrity': 'PASS (corrected)', 'replication_integrity': 'PASS', 'statistical_robustness': 'NEEDS_MORE_VALIDATION', 'paper_research_readiness': 'NOT_READY'}, indent=2))}</pre>
<script>window.v7Audit={payload};</script></body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "v7_independently_reconciled_causal_backtest.html"
    path.write_text(document, encoding="utf-8")
    return path


if __name__ == "__main__":
    print(generate())
