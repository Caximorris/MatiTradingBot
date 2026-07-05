#!/usr/bin/env python
"""Print PropSwing/CFT operational status for cron, SSH, and Telegram debugging."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true",
                   help="exit 2 if the monitor is in hard_stop")
    args = p.parse_args()

    from core.cft_monitor import format_status, load_status, read_events

    status = load_status()
    if args.json:
        print(json.dumps(status, sort_keys=True))
    else:
        print(format_status(status))
        events = read_events(limit=5)
        if events:
            print("last_events")
            for e in events:
                print(json.dumps(e, sort_keys=True))
    return 2 if args.strict and status.get("hard_stop") else 0


if __name__ == "__main__":
    raise SystemExit(main())
