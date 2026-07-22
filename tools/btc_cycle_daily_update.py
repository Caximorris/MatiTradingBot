"""Daily research-only BTC cycle evidence refresh."""
import argparse
from datetime import datetime, timezone

from btc_cycle_audit.cli import parser

if __name__ == "__main__":
    outer = argparse.ArgumentParser()
    outer.add_argument("--start", default="2015-01-01")
    outer.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    args = outer.parse_args()
    cli_args = parser().parse_args(["daily", "--start", args.start, "--end", args.end])
    cli_args.func(cli_args)
