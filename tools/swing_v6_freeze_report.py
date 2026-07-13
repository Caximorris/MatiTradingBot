"""Canonical anchor report for the frozen Swing Allocator v6-2 default.

Usage:
    python tools/swing_v6_freeze_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.swing_v5_freeze_report import print_report


V6_CONFIG = {
    "use_phase_policy_router": True,
    "phase_policy_profile": "v5_equiv",
    "use_funding_overlay": True,
    "funding_overlay_phases": "accumulation",
    "funding_overlay_delta": 0.05,
    "funding_low_pctile": 0.10,
    "funding_high_pctile": 0.90,
    "funding_overlay_lookback_settlements": 90,
    "funding_overlay_ttl_days": 7,
    "funding_overlay_dedup_days": 7,
}


if __name__ == "__main__":
    print_report(V6_CONFIG)
