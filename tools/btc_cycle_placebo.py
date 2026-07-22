"""Run the pre-registered false-calendar comparison."""
from btc_cycle_audit.cli import parser

if __name__ == "__main__":
    args = parser().parse_args(["placebo"])
    args.func(args)
