"""Command line entrypoint for the isolated BTC cycle audit."""
from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .core import boundary_stats, canonical_json, consensus_daily, causal_confirmations, immutable_snapshot, retrospective_extremes, sha256_bytes, validate_bars
from .models import PriceBar
from .sources import blockstream_halving, estimate_next_halving, fetch_source, get_text, now_utc, write_source_snapshot


ROOT = Path(__file__).resolve().parents[2]
AUDIT_ROOT = ROOT / "data" / "btc_cycle_audit"
CONFIRMED_HEIGHTS = (210_000, 420_000, 630_000, 840_000)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: object) -> str:
    data = canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def cmd_halvings(args: argparse.Namespace) -> None:
    blocks = [blockstream_halving(height, cache_dir=AUDIT_ROOT / "blocks") for height in CONFIRMED_HEIGHTS]
    tip = int(get_text("https://blockstream.info/api/blocks/tip/height"))
    estimate = estimate_next_halving(tip_height=tip, last_halving_height=CONFIRMED_HEIGHTS[-1], last_halving_time=blocks[-1].block_timestamp_utc)
    payload = {"confirmed_halvings": [block.__dict__ for block in blocks], "estimated_next_halving": estimate, "generated_at": now_utc()}
    digest = save_json(AUDIT_ROOT / "snapshots" / f"halvings_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json", payload)
    save_json(AUDIT_ROOT / "current_halvings.json", {**payload, "dataset_hash": digest})
    print(json.dumps({"dataset_hash": digest, **payload}, indent=2))


def cmd_prices(args: argparse.Namespace) -> None:
    start = int(datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc).timestamp())
    end = int(datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc).timestamp())
    all_rows: list[dict] = []
    manifests: list[dict] = []
    for source in ("coinbase", "bitstamp", "kraken"):
        rows, snapshot = fetch_source(source, start, end)
        path = write_source_snapshot(AUDIT_ROOT / "sources", rows, snapshot)
        errors, counts = validate_bars(rows)
        manifests.append({"snapshot": snapshot.__dict__, "path": str(path.relative_to(ROOT)), "validation": counts, "errors": errors[:100]})
        all_rows.extend(row.__dict__ for row in rows)
    digest = save_json(AUDIT_ROOT / "snapshots" / f"prices_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json", {"sources": manifests, "rows": all_rows, "generated_at": now_utc()})
    save_json(AUDIT_ROOT / "current_prices.json", {"sources": manifests, "rows": all_rows, "dataset_hash": digest})
    print(json.dumps({"dataset_hash": digest, "sources": manifests}, indent=2))


def _load_consensus() -> tuple[dict, list[dict]]:
    prices = load_json(AUDIT_ROOT / "current_prices.json")
    bars = [PriceBar(**row) for row in prices["rows"]]
    return prices, consensus_daily(bars)


def cmd_audit(args: argparse.Namespace) -> None:
    halving_payload = load_json(AUDIT_ROOT / "current_halvings.json")
    prices, consensus = _load_consensus()
    extremes = retrospective_extremes(consensus, halving_payload["confirmed_halvings"], include_incomplete=True)
    by_kind = {"top_close": [x.days_since_halving for x in extremes if x.kind == "top" and x.method == "close" and x.status == "RETROSPECTIVE"], "top_intraday": [x.days_since_halving for x in extremes if x.kind == "top" and x.method == "intraday" and x.status == "RETROSPECTIVE"], "bottom_close": [x.days_since_halving for x in extremes if x.kind == "bottom" and x.method == "close" and x.status == "RETROSPECTIVE"], "bottom_intraday": [x.days_since_halving for x in extremes if x.kind == "bottom" and x.method == "intraday" and x.status == "RETROSPECTIVE"]}
    payload = {"prices_dataset_hash": prices.get("dataset_hash"), "consensus": consensus, "extremes": [x.__dict__ for x in extremes], "stats": {"top_close": boundary_stats(by_kind["top_close"], 540).__dict__, "top_intraday": boundary_stats(by_kind["top_intraday"], 540).__dict__, "bottom_close": boundary_stats(by_kind["bottom_close"], 900).__dict__, "bottom_intraday": boundary_stats(by_kind["bottom_intraday"], 900).__dict__}, "generated_at": now_utc()}
    digest = immutable_snapshot(AUDIT_ROOT / "snapshots" / f"audit_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json", payload)
    save_json(AUDIT_ROOT / "current_audit.json", {**payload, "dataset_hash": digest})
    print(json.dumps({"dataset_hash": digest, "extremes": payload["extremes"], "stats": payload["stats"]}, indent=2))


def cmd_causal(args: argparse.Namespace) -> None:
    _, consensus = _load_consensus()
    halvings = load_json(AUDIT_ROOT / "current_halvings.json")["confirmed_halvings"]
    events: list[dict] = []
    for index, halving in enumerate(halvings):
        start = halving["block_timestamp_utc"][:10]
        end = halvings[index + 1]["block_timestamp_utc"][:10] if index + 1 < len(halvings) else None
        rows = [row for row in consensus if row["date_utc"] >= start and (end is None or row["date_utc"] < end)]
        if not rows or rows[0]["date_utc"] > start:
            continue
        for event in causal_confirmations(rows, drawdown_pct=__import__("decimal").Decimal(str(args.drawdown)), recovery_pct=__import__("decimal").Decimal(str(args.recovery)), confirmation_days=args.days):
            events.append({"cycle": f"{start[:4]}_cycle", **event})
    payload = {"rules": {"drawdown_pct": args.drawdown, "recovery_pct": args.recovery, "confirmation_days": args.days}, "events": events, "generated_at": now_utc()}
    digest = immutable_snapshot(AUDIT_ROOT / "snapshots" / f"causal_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json", payload)
    print(json.dumps({"dataset_hash": digest, **payload}, indent=2))


def cmd_sensitivity(args: argparse.Namespace) -> None:
    cases = [(bear, accumulation, args.start, args.end, args.costs) for bear in (480, 510, 540, 570, 600) for accumulation in (840, 870, 900, 930, 960)]
    with ProcessPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(_sensitivity_case, cases))
    rows.sort(key=lambda row: (row["bear_defense_start"], row["accumulation_start"]))
    save_json(AUDIT_ROOT / "sensitivity_5x5.json", {"matrix": rows, "generated_at": now_utc(), "costs": args.costs})
    print(json.dumps(rows, indent=2))


def _sensitivity_case(case: tuple[int, int, str, str, str]) -> dict:
    from loguru import logger
    logger.remove()
    bear, accumulation, start_raw, end_raw, costs = case
    try:
        from tools.swing_v6_common import load_bars, metrics_row, run_swing_backtest
    except ModuleNotFoundError:
        from swing_v6_common import load_bars, metrics_row, run_swing_backtest
    from datetime import datetime
    start = datetime.fromisoformat(start_raw).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_raw).replace(tzinfo=timezone.utc)
    bars = load_bars("BTC-USDT", start, end)
    run = run_swing_backtest(symbol="BTC-USDT", from_dt=start, to_dt=end, cost_mode=costs, config={"phase_post_end": 180, "phase_peak_end": bear, "phase_onset_end": accumulation, "use_funding_overlay": False}, bars=bars)
    return metrics_row(f"bear_{bear}_accum_{accumulation}", run, {"bear_defense_start": bear, "accumulation_start": accumulation})


def cmd_placebo(args: argparse.Namespace) -> None:
    audit = load_json(AUDIT_ROOT / "current_audit.json")
    actual = audit.get("stats", {})
    shifts = (-365, -180, 180, 365)
    payload = {"fixed_durations": {"bear_defense_start": 540, "accumulation_start": 900}, "actual_calendar": "confirmed_halvings", "placebos": [{"label": f"shift_{shift:+d}d", "shift_days": shift} for shift in shifts], "actual_cycle_stats": actual, "seed": args.seed, "status": "RESEARCH_ONLY", "generated_at": now_utc()}
    digest = immutable_snapshot(AUDIT_ROOT / "snapshots" / f"placebo_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json", payload)
    save_json(AUDIT_ROOT / "placebo.json", {**payload, "dataset_hash": digest})
    print(json.dumps(payload, indent=2))


def cmd_daily(args: argparse.Namespace) -> None:
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    cmd_halvings(argparse.Namespace())
    cmd_prices(argparse.Namespace(start=args.start, end=args.end))
    cmd_audit(argparse.Namespace())
    halving = load_json(AUDIT_ROOT / "current_halvings.json")["confirmed_halvings"][-1]
    audit = load_json(AUDIT_ROOT / "current_audit.json")
    try:
        commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit_hash = "UNKNOWN"
    prediction = {
        "halving_confirmed_at": halving["block_timestamp_utc"],
        "active_strategy_version": "v6-2",
        "bear_defense_start": 540,
        "accumulation_start": 900,
        "top_window_prediction": {"center": 540, "lower": 480, "upper": 600, "status": "ACTIVE_ASSUMPTION"},
        "bottom_window_prediction": {"center": 900, "lower": 840, "upper": 960, "status": "ACTIVE_ASSUMPTION"},
        "created_at": now_utc(),
        "commit_hash": commit_hash,
        "dataset_hash": audit.get("prices_dataset_hash", ""),
    }
    original = AUDIT_ROOT / "original_prediction.json"
    if not original.exists():
        immutable_snapshot(original, prediction)
    current = {"original_prediction": json.loads(original.read_text(encoding="utf-8")), "current_observation": {"cycle": "2024_cycle", "days_since_halving": (datetime.now(timezone.utc).date() - datetime.fromisoformat(halving["block_timestamp_utc"].replace("Z", "+00:00")).date()).days, "extremes": [row for row in audit.get("extremes", []) if row["cycle"] == "2024_cycle"], "updated_at": now_utc()}, "revised_research_candidate": None, "active_production_policy": {"version": "v6-2", "bear_defense_start": 540, "accumulation_start": 900}}
    save_json(AUDIT_ROOT / "current_observation.json", current)
    alerts = []
    for source in load_json(AUDIT_ROOT / "current_prices.json").get("sources", []):
        if source["snapshot"]["status"] != "OK" or source["validation"].get("stale"):
            alerts.append({"type": "SOURCE_QUALITY", "source": source["snapshot"]["source"], "status": source["snapshot"]["status"], "validation": source["validation"]})
    alerts.append({"type": "INCOMPLETE_CYCLE", "cycle": "2024_cycle", "message": "current top/bottom remain provisional"})
    save_json(AUDIT_ROOT / "alerts.json", {"alerts": alerts, "active_strategy_changed": False, "generated_at": now_utc()})
    print(json.dumps({"status": "RESEARCH_ONLY", "active_strategy_changed": False, "alerts": alerts, "updated_at": now_utc()}, indent=2))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Research-only Bitcoin halving phase audit")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("halvings").set_defaults(func=cmd_halvings)
    prices = sub.add_parser("prices")
    prices.add_argument("--start", default="2015-01-01")
    prices.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    prices.set_defaults(func=cmd_prices)
    sub.add_parser("audit").set_defaults(func=cmd_audit)
    causal = sub.add_parser("causal")
    causal.add_argument("--drawdown", type=float, default=.20)
    causal.add_argument("--recovery", type=float, default=.20)
    causal.add_argument("--days", type=int, default=60)
    causal.set_defaults(func=cmd_causal)
    sensitivity = sub.add_parser("sensitivity")
    sensitivity.add_argument("--start", default="2015-01-01")
    sensitivity.add_argument("--end", default="2026-01-01")
    sensitivity.add_argument("--costs", default="realistic")
    sensitivity.set_defaults(func=cmd_sensitivity)
    placebo = sub.add_parser("placebo")
    placebo.add_argument("--seed", type=int, default=42)
    placebo.set_defaults(func=cmd_placebo)
    daily = sub.add_parser("daily")
    daily.add_argument("--start", default="2015-01-01")
    daily.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    daily.set_defaults(func=cmd_daily)
    return p


if __name__ == "__main__":
    parser().parse_args().func(parser().parse_args())
