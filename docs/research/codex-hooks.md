# Lightweight Codex hooks

Hooks protect the repository; they do not run research or decide whether a strategy is ready for
paper. The active lifecycle in `.codex/hooks.json` is deliberately small:

| Event | What it does |
| --- | --- |
| SessionStart | Stores a local baseline in the OS temp directory. |
| PreToolUse | Blocks unsafe mutations: secrets, protected paths, frozen defaults, live/stateful commands, and unclassified shell commands. |
| PostToolUse | Checks changed Python syntax, new `requests` imports, and 800-line regressions. |

There are no `Stop`, `SubagentStart`, or `SubagentStop` hooks. A normal implementation may finish
without specialist receipts, a Tier 3 suite, or a recursive continuation. Agents are an optional
research tool, not a hook requirement.

## What remains enforced

- `git commit` runs the targeted Tier 2 checks for staged changed categories.
- An explicit Tier 3 validation or PR creation can require the full engineering receipt and the
  applicable independent evidence. Use this for default/live promotion, not isolated paper candidates.
- `python main.py backtest` is allowed only as a bounded local offline command. `start`, `stop`,
  paper-fleet/candidate setup, demo smoke, and other mutating operations remain denied by hooks.
- A push to a `codex/*` branch is classifiable, but remains a separate explicit user-authorized action.

## Candidate workflow

Use [candidate-paper-workflow.md](../forward-test/candidate-paper-workflow.md). The required path is:
implement → deterministic backtests → fix defects → lookahead/overfitting falsification → full
engineering checks → `PAPER_CANDIDATE_READY`. Default/live promotion is deliberately later.

Inspect or explicitly validate hooks with:

```powershell
python .codex/hooks/research_guard.py describe
python .codex/hooks/research_guard.py validate --tier 2 --reason local-check
python .codex/hooks/research_guard.py validate --tier 3 --reason promotion
```

Hook state is OS-temporary. It never reads raw journals, launches agents, edits data, or starts bots.
