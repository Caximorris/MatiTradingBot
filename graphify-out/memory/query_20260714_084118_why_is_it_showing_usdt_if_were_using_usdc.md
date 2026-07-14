---
type: "query"
date: "2026-07-14T08:41:18.663538+00:00"
question: "why is it showing usdt if were using usdc?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["status()", "OKXDemoClient", "._exec_symbol()", "test_exec_quote_aliases_usdc_balance_as_usdt()"]
---

# Q: why is it showing usdt if were using usdc?

## Answer

Expanded from original query via graph vocab: [status, balance, paper, usdt, usdc, demo, execution, quote, client, portfolio, symbol, alias]. main.py status creates the unnamed default OKXClient and reads data/runtime/paper_state.json, so its Balance block is not the isolated OKX Demo account. BotState keeps BTC-USDT as the strategy/feed symbol. OKXDemoClient translates BTC-USDT orders to BTC-USDC and deliberately aliases the returned USDC balance back to USDT for strategy compatibility. CFT  is normalized monitor equity, not an exchange cash balance. Reporting should label each portfolio separately and show Demo as USDC with the internal USDT alias disclosed.

## Outcome

- Signal: useful

## Source Nodes

- status()
- OKXDemoClient
- ._exec_symbol()
- test_exec_quote_aliases_usdc_balance_as_usdt()