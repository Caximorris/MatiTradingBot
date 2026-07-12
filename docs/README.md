# docs/

Deeper documentation for MatiTradingBot. The repo root keeps only the front door (`README.md`), the
license, the experiment registry (`EXPERIMENTS.md` — accepted/rejected/parked strategy ideas; check
it before proposing a change), and the AI-agent working files (`CLAUDE.md`, `AGENTS.md`,
`SESSION.md`) that the harness loads on startup. Everything else — design, audits, ops runbooks,
forward-test rules, history — lives here.

> Most of these are internal working notes (Spanish, session-driven). They're kept for
> reproducibility and future iterations, not as polished prose.

## Swing Allocator (the flagship)

- [`swing/plan.md`](swing/plan.md) — design and go/no-go validation plan.
- [`swing/v6-plan.md`](swing/v6-plan.md) — experimental v6 successor (phase-router + funding overlay).
- [`swing/audits.md`](swing/audits.md) — consolidated quantitative audit: v4 findings, the F1–F19
  remediation plan, and the v5 post-implementation freeze review.

## Prop firm research

- [`prop/hyrotrader-plan.md`](prop/hyrotrader-plan.md) — full HyroTrader / CFT / Bybit challenge
  research: rule simulators, phase-router, verdicts.

## Forward test

- [`forward-test/contract.md`](forward-test/contract.md) — frozen rules of the paper forward test
  (start 2026-07-04): strategy-failure vs infra-failure taxonomy.
- [`forward-test/research-lab-plan.md`](forward-test/research-lab-plan.md) — observability + research
  lab roadmap.

## Operations

- [`ops/deploy-paper.md`](ops/deploy-paper.md) — cloud paper-trading runbook (GCP VM, systemd,
  Telegram, daily checks).

## Archive

- [`archive/session-archive.md`](archive/session-archive.md) — full historical session logs, backtest
  tables, per-module reference (read on demand).
- [`archive/refactor-backlog.md`](archive/refactor-backlog.md) — deferred code-cleanup backlog.

## Handoff

- [`handoff.md`](handoff.md) — full context to resume work from another machine.
