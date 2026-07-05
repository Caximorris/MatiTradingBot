"""Telegram formatting helpers for PropSwing/CFT monitoring."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROP_JOURNAL = ROOT / "data" / "runtime" / "prop_live_journal.jsonl"


def _esc(s) -> str:
    return html.escape(str(s), quote=False)


def read_jsonl(path: Path, limit: int = 20) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def format_prop_status(rows, max_age_min: int = 10) -> str:
    from core.cft_monitor import format_status as fmt_cft, load_status
    lines = ["\U0001F3AF <b>PROP/CFT — PAPER</b>", ""]
    if not rows:
        lines.append("Sin bots prop configurados.")
    for r in rows:
        if not r.is_active:
            state, icon = "PAUSADO", "⏸"
        elif r.last_run is None:
            state, icon = "ACTIVO (sin tick aun)", "\U0001F7E1"
        else:
            last = r.last_run if r.last_run.tzinfo else r.last_run.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last).total_seconds() / 60
            icon = "\U0001F7E2" if age <= max_age_min else "\U0001F534"
            state = f"ultimo tick hace {age:.0f} min"
        lines.append(f"{icon} <b>{_esc(r.strategy_name)}</b> [{_esc(r.symbol)}]: {state}")
    lines.append("")
    lines.append("<pre>" + _esc(fmt_cft(load_status())) + "</pre>")
    events = read_jsonl(PROP_JOURNAL, 5)
    if events:
        lines.append("")
        lines.append("<b>Ultimos eventos</b>")
        for e in events:
            bits = [e.get("ts", "?")[5:16], e.get("kind", "?")]
            if e.get("decision"):
                bits.append(e["decision"])
            if e.get("reason"):
                bits.append(e["reason"])
            if e.get("side"):
                bits.append(e["side"])
            if e.get("pnl") is not None:
                bits.append(f"pnl={float(e['pnl']):+.2f}")
            lines.append(_esc(" | ".join(bits)))
    return "\n".join(lines)


def format_prop_report(n: int = 20) -> str:
    events = read_jsonl(PROP_JOURNAL, n)
    if not events:
        return "Sin eventos PropSwing registrados aun."
    body = []
    for e in events:
        body.append(_esc(
            f"{e.get('ts', '?')[5:16]} {e.get('kind', '?'):6} "
            f"{e.get('decision', '') or e.get('side', ''):8} "
            f"{e.get('reason', '')} {e.get('rule_state', '')} "
            f"{e.get('pnl', '')}"
        ))
    return "\U0001F4D2 <b>PROP REPORT</b>\n<pre>" + "\n".join(body) + "</pre>"
