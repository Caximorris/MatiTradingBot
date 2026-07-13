# OKXClient — complete connection trace

Source node: `core/exchange.py L100`
Direct degree: **82** connections.
Two-hop reach: **420** additional nodes across **38** communities.

## Confidence summary

- EXTRACTED: 62
- INFERRED: 20

## Relation summary

- `method`: 30
- `uses`: 19
- `imports`: 15
- `references`: 11
- `calls`: 4
- `contains`: 1
- `rationale_for`: 1
- `indirect_call`: 1

## Direct connections (all 82)

| Community | Node | Direction | Relation | Confidence | Source |
|---|---|---:|---|---|---|
| Adaptive Trend Bot | `.__init__()` | `<--` | `references` | EXTRACTED | `strategies/adaptive_trend.py L140` |
| Adaptive Trend Bot | `AdaptiveTrendBot` | `<--` | `uses` | INFERRED | `strategies/adaptive_trend.py L125` |
| Adaptive Trend Bot | `AdaptiveTrendConfig` | `<--` | `uses` | INFERRED | `strategies/adaptive_trend.py L51` |
| Adaptive Trend Indicators | `adaptive_trend.py` | `<--` | `imports` | EXTRACTED | `strategies/adaptive_trend.py L1` |
| Adaptive Trend Indicators | `pro_trend.py` | `<--` | `imports` | EXTRACTED | `strategies/pro_trend.py L1` |
| Adaptive Trend Indicators | `scalp_momentum.py` | `<--` | `imports` | EXTRACTED | `strategies/scalp_momentum.py L1` |
| Backtest Client Interface | `main()` | `<--` | `calls` | EXTRACTED | `tools/swing_parity_check.py L44` |
| Backtest Client Interface | `swing_parity_check.py` | `<--` | `imports` | EXTRACTED | `tools/swing_parity_check.py L1` |
| Bot State Risk | `_make_client()` | `<--` | `indirect_call` | INFERRED | `tests/test_risk_manager.py L58` |
| Bot State Risk | `RiskManager` | `<--` | `uses` | INFERRED | `core/risk_manager.py L18` |
| Bot State Risk | `test_risk_manager.py` | `<--` | `imports` | EXTRACTED | `tests/test_risk_manager.py L1` |
| Exchange Client Tests | `_live_client()` | `<--` | `references` | EXTRACTED | `tests/test_exchange.py L364` |
| Exchange Client Tests | `_persistent_client()` | `<--` | `references` | EXTRACTED | `tests/test_exchange.py L320` |
| Exchange Client Tests | `client()` | `<--` | `references` | EXTRACTED | `tests/test_exchange.py L36` |
| Exchange Client Tests | `test_exchange.py` | `<--` | `imports` | EXTRACTED | `tests/test_exchange.py L1` |
| Exchange Client Tests | `test_paper_state_name_isolates_persisted_balances()` | `<--` | `calls` | EXTRACTED | `tests/test_exchange.py L69` |
| Exchange Settings Errors | `.__init__()` | `<--` | `calls` | EXTRACTED | `core/okx_demo_client.py L69` |
| Exchange Settings Errors | `.__init__()` | `<--` | `references` | EXTRACTED | `core/risk_manager.py L19` |
| Exchange Settings Errors | `._check_okx_response()` | `-->` | `method` | EXTRACTED | `core/exchange.py L170` |
| Exchange Settings Errors | `okx_demo_client.py` | `<--` | `imports` | EXTRACTED | `core/okx_demo_client.py L1` |
| Exchange Settings Errors | `Settings` | `-->` | `uses` | INFERRED | `config/settings.py L67` |
| Forward Report Tests | `.__init__()` | `<--` | `references` | EXTRACTED | `strategies/base_strategy.py L22` |
| Funding Extreme Strategy | `FundingExtremeBot` | `<--` | `uses` | INFERRED | `strategies/funding_extreme.py L155` |
| Funding Signal Tests | `FundingExtremeConfig` | `<--` | `uses` | INFERRED | `strategies/funding_extreme.py L96` |
| Indicators Data Audit | `_CacheEntry` | `<--` | `uses` | INFERRED | `data/market_data.py L27` |
| Indicators Data Audit | `market_data.py` | `<--` | `imports` | EXTRACTED | `data/market_data.py L1` |
| Indicators Data Audit | `MarketDataCache` | `<--` | `uses` | INFERRED | `data/market_data.py L32` |
| Indicators Data Audit | `OHLCVBar` | `<--` | `uses` | INFERRED | `data/market_data.py L17` |
| Live Operations CLI | `_make_client()` | `<--` | `calls` | EXTRACTED | `cli/common.py L162` |
| OKX Demo Client | `OKXDemoClient` | `<--` | `uses` | INFERRED | `core/okx_demo_client.py L66` |
| OKX Live Client | `.__init__()` | `-->` | `method` | EXTRACTED | `core/exchange.py L103` |
| OKX Live Client | `._call_api()` | `-->` | `method` | EXTRACTED | `core/exchange.py L177` |
| OKX Live Client | `._init_apis()` | `-->` | `method` | EXTRACTED | `core/exchange.py L137` |
| OKX Live Client | `._live_cancel_order()` | `-->` | `method` | EXTRACTED | `core/exchange.py L678` |
| OKX Live Client | `._load_paper_state()` | `-->` | `method` | EXTRACTED | `core/exchange.py L707` |
| OKX Live Client | `._paper_cancel_order()` | `-->` | `method` | EXTRACTED | `core/exchange.py L528` |
| OKX Live Client | `._safe_state_name()` | `-->` | `method` | EXTRACTED | `core/exchange.py L195` |
| OKX Live Client | `.cancel_order()` | `-->` | `method` | EXTRACTED | `core/exchange.py L392` |
| OKX Live Client | `.get_balance()` | `-->` | `method` | EXTRACTED | `core/exchange.py L283` |
| OKX Live Client | `.get_funding_rate()` | `-->` | `method` | EXTRACTED | `core/exchange.py L365` |
| OKX Live Client | `.get_ohlcv()` | `-->` | `method` | EXTRACTED | `core/exchange.py L213` |
| OKX Live Client | `.get_open_orders()` | `-->` | `method` | EXTRACTED | `core/exchange.py L313` |
| OKX Live Client | `.get_order_history()` | `-->` | `method` | EXTRACTED | `core/exchange.py L346` |
| OKX Live Client | `.get_paper_orders()` | `-->` | `method` | EXTRACTED | `core/exchange.py L702` |
| OKX Live Client | `.get_positions()` | `-->` | `method` | EXTRACTED | `core/exchange.py L332` |
| OKX Live Client | `.is_available()` | `-->` | `method` | EXTRACTED | `core/exchange.py L754` |
| OKX Live Client | `.is_paper()` | `-->` | `method` | EXTRACTED | `core/exchange.py L750` |
| OKX Live Client | `client_with_ticker()` | `<--` | `references` | EXTRACTED | `tests/test_exchange.py L47` |
| OKX Live Client | `Interfaz unificada para OKX.` | `<--` | `rationale_for` | EXTRACTED | `core/exchange.py L101` |
| Paper Exchange Execution | `._live_place_order()` | `-->` | `method` | EXTRACTED | `core/exchange.py L627` |
| Paper Exchange Execution | `._next_paper_id()` | `-->` | `method` | EXTRACTED | `core/exchange.py L397` |
| Paper Exchange Execution | `._paper_check_and_deduct()` | `-->` | `method` | EXTRACTED | `core/exchange.py L501` |
| Paper Exchange Execution | `._paper_place_order()` | `-->` | `method` | EXTRACTED | `core/exchange.py L401` |
| Paper Exchange Execution | `._persist_paper_state()` | `-->` | `method` | EXTRACTED | `core/exchange.py L728` |
| Paper Exchange Execution | `._utcnow()` | `-->` | `method` | EXTRACTED | `core/exchange.py L191` |
| Paper Exchange Execution | `.adjust_balance()` | `-->` | `method` | EXTRACTED | `core/exchange.py L304` |
| Paper Exchange Execution | `.current_time()` | `-->` | `method` | EXTRACTED | `core/exchange.py L199` |
| Paper Exchange Execution | `.fill_paper_limit_orders()` | `-->` | `method` | EXTRACTED | `core/exchange.py L551` |
| Paper Exchange Execution | `.get_ticker()` | `-->` | `method` | EXTRACTED | `core/exchange.py L202` |
| Paper Exchange Execution | `.place_order()` | `-->` | `method` | EXTRACTED | `core/exchange.py L379` |
| Paper Exchange Execution | `.set_paper_balance()` | `-->` | `method` | EXTRACTED | `core/exchange.py L696` |
| Performance Breakdown Metrics | `common.py` | `<--` | `imports` | EXTRACTED | `cli/common.py L1` |
| Pro Trend Engine | `ProTrendBot` | `<--` | `uses` | INFERRED | `strategies/pro_trend.py L315` |
| Pro Trend Engine | `ProTrendConfig` | `<--` | `uses` | INFERRED | `strategies/pro_trend.py L62` |
| Prop Swing Engine | `PropSwingBot` | `<--` | `uses` | INFERRED | `strategies/prop_swing.py L149` |
| Prop Swing Engine | `PropSwingConfig` | `<--` | `uses` | INFERRED | `strategies/prop_swing.py L65` |
| Range Reversion Strategy | `.__init__()` | `<--` | `references` | EXTRACTED | `strategies/range_reversion.py L154` |
| Range Reversion Strategy | `RangeReversionBot` | `<--` | `uses` | INFERRED | `strategies/range_reversion.py L134` |
| Range Reversion Strategy | `RangeReversionConfig` | `<--` | `uses` | INFERRED | `strategies/range_reversion.py L57` |
| Scalp Momentum Strategy | `ScalpMomentumBot` | `<--` | `uses` | INFERRED | `strategies/scalp_momentum.py L218` |
| Scalp Momentum Strategy | `ScalpMomentumConfig` | `<--` | `uses` | INFERRED | `strategies/scalp_momentum.py L61` |
| Strategy Exchange Abstractions | `base_strategy.py` | `<--` | `imports` | EXTRACTED | `strategies/base_strategy.py L1` |
| Strategy Exchange Abstractions | `BaseStrategy` | `<--` | `uses` | INFERRED | `strategies/base_strategy.py L21` |
| Strategy Exchange Abstractions | `exchange.py` | `<--` | `contains` | EXTRACTED | `core/exchange.py L1` |
| Strategy Exchange Abstractions | `funding_extreme.py` | `<--` | `imports` | EXTRACTED | `strategies/funding_extreme.py L1` |
| Strategy Exchange Abstractions | `prop_swing.py` | `<--` | `imports` | EXTRACTED | `strategies/prop_swing.py L1` |
| Strategy Exchange Abstractions | `range_reversion.py` | `<--` | `imports` | EXTRACTED | `strategies/range_reversion.py L1` |
| Strategy Exchange Abstractions | `risk_manager.py` | `<--` | `imports` | EXTRACTED | `core/risk_manager.py L1` |
| Terminal Dashboard | `_balance_panel()` | `<--` | `references` | EXTRACTED | `reporting/dashboard.py L61` |
| Terminal Dashboard | `_render()` | `<--` | `references` | EXTRACTED | `reporting/dashboard.py L223` |
| Terminal Dashboard | `dashboard.py` | `<--` | `imports` | EXTRACTED | `reporting/dashboard.py L1` |
| Terminal Dashboard | `run_dashboard()` | `<--` | `references` | EXTRACTED | `reporting/dashboard.py L249` |

## Representative shortest paths

- **SwingAllocatorBot** (2 hops): `OKXClient --imports [EXTRACTED]--> swing_parity_check.py --imports [EXTRACTED]--> SwingAllocatorBot`
- **BacktestClient** (2 hops): `OKXClient --uses [INFERRED]--> OHLCVBar --uses [INFERRED]--> BacktestClient`
- **BacktestEngine** (2 hops): `OKXClient --uses [INFERRED]--> OHLCVBar --uses [INFERRED]--> BacktestEngine`
- **RiskManager** (1 hops): `OKXClient --uses [INFERRED]--> RiskManager`
- **OKXDemoClient** (1 hops): `OKXClient --uses [INFERRED]--> OKXDemoClient`
- **BotState** (2 hops): `OKXClient --imports [EXTRACTED]--> risk_manager.py --imports [EXTRACTED]--> BotState`
- **TradeLogger** (2 hops): `OKXClient --imports [EXTRACTED]--> base_strategy.py --imports [EXTRACTED]--> TradeLogger`
- **telegram_remote.py** (3 hops): `OKXClient --imports [EXTRACTED]--> risk_manager.py --imports [EXTRACTED]--> BotState --imports [EXTRACTED]--> telegram_remote.py`
- **ProTrendBot** (1 hops): `OKXClient --uses [INFERRED]--> ProTrendBot`
- **PropSwingBot** (1 hops): `OKXClient --uses [INFERRED]--> PropSwingBot`
- **ScalpMomentumBot** (1 hops): `OKXClient --uses [INFERRED]--> ScalpMomentumBot`
- **RangeReversionBot** (1 hops): `OKXClient --uses [INFERRED]--> RangeReversionBot`

## Two-hop community reach

- Bot State Risk: 39 nodes
- Pro Trend Engine: 36 nodes
- Prop Swing Engine: 36 nodes
- Scalp Momentum Strategy: 34 nodes
- Exchange Client Tests: 29 nodes
- OKX Demo Client: 27 nodes
- Indicators Data Audit: 24 nodes
- Adaptive Trend Indicators: 24 nodes
- Strategy Exchange Abstractions: 19 nodes
- Range Reversion Strategy: 18 nodes
- Adaptive Trend Bot: 16 nodes
- Terminal Dashboard: 14 nodes
- Performance Breakdown Metrics: 12 nodes
- Funding Extreme Strategy: 12 nodes
- Exchange Settings Errors: 8 nodes
- Database Trading Models: 7 nodes
- Live Operations CLI: 6 nodes
- Paper Exchange Execution: 6 nodes
- Backtest Execution Engine: 5 nodes
- Funding Signal Tests: 5 nodes
- Backtest CLI Commands: 4 nodes
- Historical Backtest Data: 4 nodes
- Bot CLI Management: 3 nodes
- Demo Client Tests: 3 nodes
- Trade Logging Models: 3 nodes
- OKX Live Client: 3 nodes
- Backtest PnL Accounting: 3 nodes
- Backtest Client Interface: 3 nodes
- Macro Halving Context: 3 nodes
- Runtime Settings: 2 nodes
- Rate Limiter Tests: 2 nodes
- OKX Demo Smoke: 2 nodes
- Market Context Data: 2 nodes
- CFT Monitoring Status: 2 nodes
- Paper Monitoring CLI: 1 nodes
- Forward Report Tests: 1 nodes
- Swing Control Tests: 1 nodes
- Swing Allocator Core: 1 nodes
