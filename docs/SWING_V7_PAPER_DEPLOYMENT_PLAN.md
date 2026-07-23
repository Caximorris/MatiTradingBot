# Swing v7 Cycle Core — paper deployment plan

## Frozen scope

V7 is an isolated, unleveraged BTC-USDT candidate. It uses only the confirmed-halving clock and the frozen 180/540/900 boundaries. It cannot run when `TRADING_MODE` is anything other than `paper`; it has no live, margin, derivatives, short, or withdrawal path.

## VM topology

The existing GCP `matitrbot` deployment runs `matibot.service` (the v6 local-paper and v6 OKX-Demo fleet), `matibot-telegram.service`, and daily cron checks. V7 extends it with `matibot-v7-shadow.service`, `matibot-v7-promotion.service`, and a gated `matibot-v7-paper.service`. The normal scheduler explicitly excludes `service_managed` v7 registrations.

## Promotion gates

The persistent controller requires all replay/parity/fault checks, unchanged dataset identity, paper verification, 72 elapsed shadow hours, 18 distinct evaluation windows, and zero duplicate transitions, fail-open events, unreconciled positions, v6 regressions, and live orders. It cannot activate the paper BotState otherwise.

## Deployment

From a committed clean checkout on the VM run `bash deploy/install_v7_paper.sh`. It snapshots v6 first, registers only shadow as active, installs the dedicated units, and starts the gate controller. The paper unit waits in `ExecStartPre` until promotion is legitimate.

The installer runs `tools/v7_operational_validation.py`, which executes the frozen operational tests and records test, v6-identity, dataset-identity, and paper-mode facts in the persistent gate state. The controller does not accept manually asserted flags as deployment evidence.

## Rollback

`sudo systemctl stop matibot-v7-paper matibot-v7-shadow matibot-v7-promotion` preserves all v7 DB rows, wallets, journals, and reports. It does not restart, reconfigure, or alter v6. Verify no unresolved local paper order, then restart only `matibot-v7-shadow` if shadow-only evidence should resume.
