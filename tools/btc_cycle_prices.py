"""Download cached multi-source BTC daily data and build source manifests."""
from btc_cycle_audit.cli import parser

if __name__ == "__main__":
    args = parser().parse_args(["prices"])
    args.func(args)
