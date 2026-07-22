"""Run the fixed 5x5 phase-boundary matrix."""
from btc_cycle_audit.cli import parser

if __name__ == "__main__":
    args = parser().parse_args(["sensitivity"])
    args.func(args)
