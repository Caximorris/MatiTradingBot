---
name: quant-model-execution
description: Specify, calibrate, and review systematic-trading execution and transaction-cost models. Use for market or limit fill semantics, signal-to-fill timing, maker/taker fees, slippage, spread, market impact, latency, queue position, partial fills, rejected orders, funding, borrow, venue constraints, or paper/backtest execution-parity analysis.
---

# Quant Execution and Cost Modelling

## Purpose

Define a defensible order-to-fill and cost contract for research. Keep venue microstructure and cost
calibration separate from strategy logic and from the independent end-to-end backtest audit.

## Trigger Conditions

Use when fills, fees, slippage, spread, impact, latency, partial fills, funding, borrow, minimums,
tick/lot sizes, or paper/backtest parity could affect a research conclusion.

## When Not to Use

- Do not judge signal edge, portfolio risk appetite, or generalization.
- Do not edit `core/backtest.py`, exchange clients, costs, orders, or funding behavior without approval.
- Do not call a stress preset calibrated merely because it is named realistic or conservative.

## Required Context

Read `AGENTS.md`, `SESSION.md`, the experiment contract, data verdict, and
`../quant-orchestrate-research/references/research-contract.md`. Inspect `core/backtest.py`,
`core/exchange.py`, `core/okx_demo_client.py`, `cli/runner.py`, funding paths, client-contract tests,
and venue documentation or measured evidence relevant to the instrument.

## Workflow

1. Trace signal timestamp -> order submission -> venue eligibility -> fill -> fee/funding -> balance.
2. Define instrument, venue, order type, size distribution, liquidity regime, and clock assumptions.
3. Separate explicit fees from spread, slippage, impact, latency, funding/borrow, and rejection costs.
4. Specify market and limit semantics, including queue, price improvement, partial fill, cancellation,
   minimum size, tick/lot rounding, and insufficient-balance behavior.
5. Calibrate assumptions from primary venue schedules, order-book/trade data, or bounded stress ranges.
6. Compare backtest, paper, demo, and live semantics; label deliberate approximations and distortions.
7. Provide deterministic representative cases and sensitivity ranges to the systems engineer.
8. Hand the implemented model to `$quant-audit-backtest` for independent validation.

## Verification Steps

- Numerically reconcile BUY, SELL, limit, partial, rejected, and funding examples.
- Confirm adverse slippage direction and fee currency on every leg.
- Confirm timing cannot use a price unavailable after the decision timestamp.
- Confirm costs scale appropriately with turnover, size, and venue constraints.
- Confirm demo-market distortions are not treated as real execution calibration.

## Expected Output

Produce an execution contract with order timeline, fill rules, fee/funding schedule, calibration
sources, stress ranges, parity gaps, deterministic examples, implementation handoff, and verdict
`CALIBRATED`, `CONSERVATIVE_PROXY`, `UNDERMODELLED`, or `INVALID`.

## Success Criteria

- Every cost and fill assumption has a source, measurement, or explicit conservative bound.
- Backtest semantics are reproducible and their differences from paper/live are visible.
- The execution specialist specifies the model but does not certify the simulator implementation.
