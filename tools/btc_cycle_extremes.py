"""Identify retrospective cycle extrema from the canonical consensus."""
from btc_cycle_audit.cli import parser

if __name__ == "__main__":
    args = parser().parse_args(["audit"])
    args.func(args)
