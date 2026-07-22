"""Render the immutable public-data audit and completed research suites."""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "btc_cycle_audit"


def esc(value: object) -> str:
    return html.escape(str(value))


def table(rows: list[dict], columns: list[str]) -> str:
    head = "".join(f"<th>{esc(column)}</th>" for column in columns)
    body = "".join("<tr>" + "".join(f"<td>{esc(row.get(column, ''))}</td>" for column in columns) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def price_svg(consensus: list[dict]) -> str:
    points = [(float(row["median_close"]), row["date_utc"]) for row in consensus if row.get("median_close")]
    if not points:
        return "<p>No canonical price points.</p>"
    stride = max(1, len(points) // 500)
    sampled = points[::stride]
    low, high = min(value for value, _ in sampled), max(value for value, _ in sampled)
    width, height = 1000, 260
    coords = []
    for index, (value, _) in enumerate(sampled):
        x = index * width / max(1, len(sampled) - 1)
        y = height - (value - low) / max(1, high - low) * (height - 20) - 10
        coords.append(f"{x:.1f},{y:.1f}")
    return f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Canonical BTC median daily close'><polyline fill='none' stroke='#62d6ff' stroke-width='1.5' points='{' '.join(coords)}'/></svg>"


def main() -> None:
    audit = json.loads((AUDIT / "current_audit.json").read_text(encoding="utf-8"))
    prices = json.loads((AUDIT / "current_prices.json").read_text(encoding="utf-8"))
    summary_path = AUDIT / "final_research_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"status": "INCOMPLETE"}
    extremes = audit.get("extremes", [])
    source_rows = [{"source": value.get("snapshot", {}).get("source"), "first": value.get("snapshot", {}).get("coverage_start_utc"), "last": value.get("snapshot", {}).get("coverage_end_utc"), "rows": value.get("snapshot", {}).get("rows"), "gaps": value.get("validation", {}).get("gaps"), "stale": value.get("validation", {}).get("stale")} for value in prices.get("sources", [])]
    matrix = []
    if summary.get("matrix", {}).get("count") == 25:
        checkpoint = json.loads((AUDIT / "research_checkpoint.json").read_text(encoding="utf-8"))
        matrix = list(checkpoint["matrix"].values())
    placebo = list(json.loads((AUDIT / "research_checkpoint.json").read_text(encoding="utf-8")).get("placebos", {}).values())
    loco = summary.get("loco", [])
    observation = json.loads((AUDIT / "current_observation.json").read_text(encoding="utf-8")) if (AUDIT / "current_observation.json").exists() else {}
    alerts = json.loads((AUDIT / "alerts.json").read_text(encoding="utf-8")) if (AUDIT / "alerts.json").exists() else {}
    candidate = json.loads((AUDIT / "revised_research_candidate.json").read_text(encoding="utf-8")) if (AUDIT / "revised_research_candidate.json").exists() else {}
    body = f"""<!doctype html><html><head><meta charset='utf-8'><title>BTC Cycle Phase Audit</title>
    <style>body{{font:14px system-ui;background:#101827;color:#e5e7eb;margin:2rem;max-width:1400px}}h1,h2{{color:#fff}}.warn{{color:#fbbf24}}.ok{{color:#86efac}}svg,table,pre{{background:#172033;border-radius:8px}}svg{{width:100%;height:280px}}table{{border-collapse:collapse;width:100%;margin:1rem 0}}th,td{{padding:6px 8px;border:1px solid #334155;text-align:left;font-size:12px}}th{{color:#93c5fd}}pre{{padding:1rem;white-space:pre-wrap;overflow:auto}}section{{margin:2rem 0}}</style></head><body>
    <h1>Bitcoin Cycle Phase Audit</h1><p class='warn'>Research-only. Active Swing policy is frozen; alerts and candidates cannot trade.</p>
    <h2>Status</h2><p class='{'ok' if summary.get('status') == 'COMPLETE' else 'warn'}'>{esc(summary.get('status'))}; matrix={esc(summary.get('matrix', {}).get('count'))}/25; placebos={esc(summary.get('placebos', {}).get('count'))}/7; LOCO={len(loco)}/2.</p>
    <section><h2>Canonical price line</h2>{price_svg(audit.get('consensus', []))}<p>UTC daily median close; source coverage and confidence are retained in the snapshot.</p></section>
    <section><h2>Halvings and cycle extrema</h2>{table(extremes, ['cycle','top_close_date','top_close_day','top_intraday_date','top_intraday_day','bottom_close_date','bottom_close_day','bottom_intraday_date','bottom_intraday_day','status'])}</section>
    <section><h2>Source coverage</h2>{table(source_rows, ['source','first','last','rows','gaps','stale'])}</section>
    <section><h2>Active boundaries and research summary</h2><pre>{esc(json.dumps({'active_boundaries': {'post_halving_end': 180, 'bear_defense_start': 540, 'accumulation_start': 900}, 'summary': summary.get('gates'), 'best_matrix_case': summary.get('matrix', {}).get('best', {}).get('case'), 'placebo_real_rank': summary.get('placebos', {}).get('real_rank_descending'), 'placebo_outperformers': summary.get('placebos', {}).get('outperforming_real')}, indent=2))}</pre></section>
    <section><h2>Confidence, current cycle, alerts, and candidate</h2><pre>{esc(json.dumps({'confidence': audit.get('stats'), 'current_cycle': observation, 'alerts': alerts, 'candidate_research_only': candidate}, indent=2))}</pre></section>
    <section><h2>5×5 sensitivity</h2>{table(matrix, ['case','bear_defense_start','accumulation_start','final','cagr','max_dd','calmar','sharpe','sortino','btc_vs_bnh_ratio','underwater_days','orders'])}</section>
    <section><h2>Placebos</h2>{table(placebo, ['label','final','cagr','max_dd','calmar','sharpe','sortino','btc_vs_bnh_ratio','underwater_days','orders'])}</section>
    <section><h2>Operational leave-one-cycle-out</h2>{table(loco, ['excluded_cycle','training_cycles','estimated_boundaries','actual_global_extrema','top_error_days','bottom_error_days','final','cagr','max_dd','btc_vs_bnh_ratio'])}</section>
    <section><h2>Raw audit metadata</h2><pre>{esc(json.dumps({'audit_dataset_hash': audit.get('dataset_hash'), 'prices_dataset_hash': prices.get('dataset_hash'), 'research_dataset_hash': summary.get('gates'), 'generated_at': audit.get('generated_at')}, indent=2))}</pre></section>
    </body></html>"""
    output = ROOT / "reporting" / "btc_cycle_phase_audit.html"
    output.write_text(body, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
