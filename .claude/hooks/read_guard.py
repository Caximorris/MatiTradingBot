#!/usr/bin/env python
"""PreToolUse guard for Read: blocks token-catastrophic reads.

Rationale (token efficiency): backtest journals are pretty-printed JSON up to ~10 MB.
A single Read of one blows the context window. This hook denies such reads and points
the model at the cheap summary path instead. Also caps any file >150 KB.

Wired from .claude/settings.json as a PreToolUse hook matching the Read tool.
Reads the tool call JSON on stdin; blocks by exiting 2 with a message on stderr
(Claude Code feeds stderr back to the model and skips the tool call).
"""
import json
import os
import sys

# Files at/above this size are blocked from raw Read regardless of type.
MAX_BYTES = 150_000
# Journals get blocked at any size — always prefer the summary tool.
JOURNAL_MARKERS = (os.path.join("backtests", "journal_"), "backtests/journal_")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never break the harness on a parse error

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if not path:
        return 0

    norm = path.replace("\\", "/")
    is_journal = "backtests/journal_" in norm and norm.endswith(".json")

    try:
        size = os.path.getsize(path)
    except OSError:
        return 0  # let Read handle missing files with its own error

    if is_journal:
        sys.stderr.write(
            f"BLOCKED: '{os.path.basename(path)}' is a backtest journal ({size:,} bytes). "
            "Reading raw journal JSON wastes the context window. Use instead:\n"
            f"  python tools/journal_summary.py \"{path}\"\n"
            "or the /journal-summary skill. For one specific field, use jq/grep on the file."
        )
        return 2

    if size >= MAX_BYTES:
        sys.stderr.write(
            f"BLOCKED: '{os.path.basename(path)}' is large ({size:,} bytes, limit {MAX_BYTES:,}). "
            "Reading it whole is token-expensive. Read a slice with offset/limit, or Grep for "
            "the specific content you need instead of loading the entire file."
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
