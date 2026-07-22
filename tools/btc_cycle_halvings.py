"""Download and verify confirmed Bitcoin halving blocks."""
from btc_cycle_audit.cli import parser

if __name__ == "__main__":
    parser().parse_args(["halvings"]).func(parser().parse_args(["halvings"]))
