"""Run pre-registered causal top/bottom confirmations."""
from btc_cycle_audit.cli import parser

if __name__ == "__main__":
    args = parser().parse_args(["causal"])
    args.func(args)
