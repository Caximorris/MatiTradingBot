# Bitcoin Cycle Phase Audit Results

Status: `RESEARCH-ONLY — public snapshot complete; strategy matrix still running`.

## Provenance already established from the repository

[Certain] The literals were introduced in the v5 post-audit commit `4c955fb` on 2026-07-02 in
`strategies/macro_context.py`, and copied into `SwingAllocatorConfig` as `phase_post_end`,
`phase_peak_end`, and `phase_onset_end`.

[Certain] `docs/swing/audits.md` states that 540 was fitted to 2017/2021 tops, was not included in
walk-forward, and that the effective independent sample was 2–3 events. It also reports a fixed
2015–2026 sensitivity where 540 was the best of the shown 480/540/600 points, while ±60 days caused
large performance changes. This is strategy evidence, not independent public-data confirmation.

[Certain] `post_halving` and `bull_peak` have identical v5-equivalent allocation targets. The 180
boundary is therefore descriptive for Swing v6-2 unless a separate consumer gives it operational
meaning; Pro Trend consumes the same phase labels and can still change behavior.

## Pending generated tables

The executable source of truth is `data/btc_cycle_audit/current_audit.json`; the HTML renderer is
`python tools/btc_cycle_report.py`. This document will be updated only with a dated, hashed result
after the public-data snapshot and fixed analyses run. No result will be presented as out-of-sample
if it contributed to design or parameter selection.

Required tables: block timestamps/hashes; source coverage; source/canonical extrema for 2012, 2016,
2020, and incomplete 2024; error distributions for 180/540/900; uncertainty windows; fixed 5x5;
placebos; LOCO; current-cycle status; alerts; and immutable prediction metadata.

## Current production statement

[Certain] v6-2 remains frozen and production/paper policy is unchanged. No candidate parameter is
available to the strategy. Any future proposal must be versioned as `RESEARCH_ONLY` and pass the
full audit, shadow mode, and human-approval gates.

## Public snapshot 2026-07-22

[Certain] Blockstream Esplora returned these confirmed block timestamps: 210000 =
2012-11-28 15:24:38 UTC; 420000 = 2016-07-09 16:46:13 UTC; 630000 = 2020-05-11 19:23:43 UTC;
840000 = 2024-04-20 00:09:27 UTC. The current tip was 959111. The next halving estimate is
2028-04-10 UTC and remains explicitly `ESTIMATED`, not a live cycle reset. Halving snapshot hash:
`d08e2330aee7291e9b86ebf050baacf03d5f895df404896d870983b97353bb91`.

[Certain] Coverage: Bitstamp 2015-01-01--2026-07-22 (4221 rows), Coinbase 2015-07-20--2026-07-22
(4021 rows), Kraken 2024-08-01--2026-07-22 (721 rows). This means the 2012 cycle is not fully
covered and is retained as an explicit insufficient-coverage case; it is not silently replaced by
the first available 2015 price. The canonical price snapshot hash is
`575485543a02e8ec2e3f0a24f4692222afe07a4c5aaef87a32b499d2361b75a6`.

| cycle | top close | days | top intraday | days | bottom close | days | bottom intraday | days | status |
|---|---|---:|---|---:|---|---:|---|---:|---|
| 2012 | unavailable | — | unavailable | — | unavailable | — | unavailable | — | insufficient coverage |
| 2016 | 2017-12-16 | 525 | 2017-12-17 | 526 | 2018-12-15 | 889 | 2018-12-15 | 889 | retrospective |
| 2020 | 2024-03-13 | 1402 | 2024-03-14 | 1403 | 2024-04-17 | 1437 | 2024-04-19 | 1439 | retrospective interval extreme |
| 2024 | 2025-10-06 | 534 | 2025-10-06 | 534 | 2026-06-30 | 801 | 2026-07-01 | 802 | provisional/incomplete |

[Likely] The 2020 interval is structurally non-comparable with the 2016 interval under a strict
"between consecutive halvings" maximum: the March 2024 pre-halving high supersedes the 2021 high.
That is evidence against using one universal day-to-top rule, not a reason to drop the cycle. A
separate first-major-bear/top label is required before using 2020 as a 540 comparison.

## Boundary measurements so far

[Certain] With only complete, covered interval cycles, 540 has close errors `-15` (2016) and `+862`
(2020), while 900 has close errors `-11` and `+537`. Intraday errors are `-14/+863` and
`-11/+539`. The sample is n=2 complete cycles; mean errors are +423.5 days for 540 and +263 days
for 900, with MAD 438.5 and 274 days respectively. Confidence is `VERY_LOW`; no narrow interval or
high-confidence claim is valid. Including the incomplete 2024 observation would be retrospective
contamination and is excluded from definitive statistics.

[Certain] 180 has no independent economic transition in the current evidence package. v5-equivalent
allocation targets are identical in post_halving and bull_peak, so 180 has no Swing operational
effect in that profile; it remains a reporting boundary and a Pro Trend consumer dependency.

## Completed fixed research suite (2026-07-22)

[Certain] The resumable checkpoint passed all gates: 25/25 sensitivity cells, 7/7 calendar
placebos, 2/2 operational LOCO cases, complete required metrics, unchanged dataset hash, and
`production_changed_by_audit=false`. The source of truth is
`data/btc_cycle_audit/final_research_summary.json`; the matrix is also exported to
`data/btc_cycle_audit/matrix_5x5.csv`.

[Certain] The best fixed cell was `(bear_defense_start=540, accumulation_start=930)`: final
capital `$10,046,134.83`, CAGR `87.45%`, maximum drawdown `-52.73%`, Calmar `1.66`, and
BTC-vs-buy-and-hold ratio `0.8983`. The worst was `(480,840)`: `$4,064,576.88`, CAGR `72.65%`,
Calmar `1.38`, ratio `0.3548`. Median final capital was `$6,111,112.95`; 13/25 cells were at or
above that median. This is not an isolated single-cell maximum, but it remains an in-sample
strategy sensitivity result, not public-data confirmation.

[Certain] The actual halving calendar ranked first of seven placebo calendars by final capital;
none of the shifted, random-seed-42, or four-year non-halving calendars outperformed it. This is
descriptive separation only: the calendars are few and the strategy was designed around phases;
no causal p-value is claimed.

[Certain] Operational LOCO is fragile. Training on 2020 and applying to 2016 estimated `1402/1437`,
errors `+877/+548` days; training on 2016 and applying to 2020 estimated `525/889`, errors
`-877/-548` days. Removing one complete cycle radically changes the estimate.

[Certain] These strategy results do not rescue the public-data hypothesis. The definitive global
extrema sample remains only two complete covered cycles, and the strict 2020 interval is dominated
by the pre-2024-halving high. Final verdict:

| boundary | verdict | confidence |
|---|---|---|
| 180 | `INSUFFICIENT_EVIDENCE` operationally; reporting-only in v5-equivalent Swing | VERY_LOW |
| 540 | `INSUFFICIENT_EVIDENCE` as exact date or validated universal center | VERY_LOW |
| 900 | `INSUFFICIENT_EVIDENCE` as stable universal bottom date | VERY_LOW |

The active production policy was not changed. Any v8 candidate must remain `RESEARCH_ONLY`, pass
the same fixed matrix/placebos/LOCO plus shadow mode, and receive explicit approval.
