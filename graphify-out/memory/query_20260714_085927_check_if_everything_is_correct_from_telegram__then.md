---
type: "query"
date: "2026-07-14T08:59:27.726681+00:00"
question: "check if everything is correct from telegram, then do those tasks about main.py status"
contributor: "graphify"
outcome: "useful"
source_nodes: ["status()", "paper_snapshot.py", "telegram_remote.py", "OKXDemoClient", "anomaly_check.py"]
---

# Q: check if everything is correct from telegram, then do those tasks about main.py status

## Answer

Expanded from original query via graph vocab: [telegram, status, balance, portfolio, paper, demo, usdc, usdt, operable, internal, snapshot, equity]. Telegram infrastructure was healthy, but reporting was not fully correct: Demo USDC was labeled USDT, hybrid Demo valuation was shown as comparable PnL, the out-of-band allocation correction was absent from the journal, and the equity caption used a different baseline than status. Implemented reporting-only fixes: main.py status now shows isolated operable wallets, signal vs execution pairs, USDC for Demo, Madrid timestamps, and no internal rows; Telegram suppresses hybrid performance, blocks invalid Demo equity, warns on Demo reports, detects >15pp Demo journal/wallet gaps, aligns V6 chart captions to INIT, and renders operational times in Europe/Madrid. Full suite: 247 passed.

## Outcome

- Signal: useful

## Source Nodes

- status()
- paper_snapshot.py
- telegram_remote.py
- OKXDemoClient
- anomaly_check.py